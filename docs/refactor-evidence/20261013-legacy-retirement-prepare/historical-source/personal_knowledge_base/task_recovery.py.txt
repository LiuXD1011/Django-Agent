"""常驻有界任务恢复 loop（MARLIN-R2B）。

替代旧的 0.1s/90.1s 两个一次性 startup Timer：此后崩溃 worker 的租约在
每个进程内由唯一的 daemon 线程按固定间隔持续扫描恢复，直到 stop_event
被置位（进程退出或 worker 命令 finally 停止）。设计约束：

- 每进程至多一个 loop 线程与一个 stop_event（``start_recovery_loop``
  幂等，返回已存活的实例）。
- 失败只记录简短错误并等待下一间隔；绝不 tight spin，也不重复创建
  Timer。每轮前后 ``close_old_connections``。
- 向量重建启动检查只在初始化首轮执行一次，不随周期重复触发全量重建；
  worker 命令可整体关闭它（worker 只恢复自己 --queue 的队列，不得在
  evaluation worker 里入队 documents 队列的重建任务）。
- 等待全部走 ``stop_event.wait(interval)``：事件驱动、间隔固定可注入，
  stop 立即打断等待；``stop`` 有限时间 join，不遗留线程。
"""

import atexit
import logging
import math
import threading

from django.db import OperationalError, ProgrammingError, close_old_connections

logger = logging.getLogger(__name__)

RECOVERY_INTERVAL_SECONDS = 30.0
STARTUP_RECOVERY_DELAY = 0.1
STOP_JOIN_TIMEOUT_SECONDS = 5.0

_loop_instance: "TaskRecoveryLoop | None" = None
_loop_lock = threading.Lock()
_atexit_stop_registered = False


def _validate_interval(value, *, label):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be a finite positive number, got {value!r}")
    return float(value)


class TaskRecoveryLoop:
    """固定间隔、事件驱动的任务恢复循环；每进程一个实例。"""

    def __init__(
        self,
        *,
        interval_seconds: float = RECOVERY_INTERVAL_SECONDS,
        initial_delay_seconds: float = STARTUP_RECOVERY_DELAY,
        queue_names=None,
        recovery_fn=None,
        startup_check_fn=None,
        include_startup_reindex_check: bool = True,
        stop_event=None,
    ):
        self.interval_seconds = _validate_interval(interval_seconds, label="interval_seconds")
        self.initial_delay_seconds = _validate_interval(initial_delay_seconds, label="initial_delay_seconds")
        self.queue_names = None if queue_names is None else tuple(str(name) for name in queue_names)
        self.include_startup_reindex_check = include_startup_reindex_check
        # 进程级幂等的契约键：queue 范围 + 是否做启动向量重建检查。
        self.contract = (
            None if self.queue_names is None else tuple(self.queue_names),
            bool(include_startup_reindex_check),
        )
        self._recovery_fn = recovery_fn
        self._startup_check_fn = startup_check_fn
        self._stop_event = stop_event or threading.Event()
        self._stopping = False
        self._thread: threading.Thread | None = None

    # -- 生命周期 ---------------------------------------------------------

    @property
    def name(self):
        return "task-recovery-loop"

    @property
    def thread(self) -> "threading.Thread | None":
        """当前 loop 线程（未 start 时为 None）；供测试断言 daemon 语义。"""
        return self._thread

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("task recovery loop is already running")
        thread = threading.Thread(target=self.run, name=self.name, daemon=True)
        self._thread = thread
        thread.start()
        return self

    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = STOP_JOIN_TIMEOUT_SECONDS) -> bool:
        """置位 stop_event 并有限时间 join；返回线程是否已终止。

        join 超时（如某轮正阻塞在卡死的 DB 回调上）时线程保持 stopping
        状态存活：调用方不得把它当正常运行实例复用，也不能再开第二个
        线程——由 is_alive/stopping 状态与 start_recovery_loop 的守卫保证。
        daemon 线程最终随进程退出，绝不阻塞 shutdown。
        """
        self._stopping = True
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return not self.is_alive()

    # -- 循环 -------------------------------------------------------------

    def run(self):
        """首次检查保留启动小延迟，之后连续周期直到 stop；同步可驱动。"""
        try:
            if self._stop_event.wait(self.initial_delay_seconds):
                return
            self._round(include_startup_check=True)
            while not self._stop_event.wait(self.interval_seconds):
                self._round(include_startup_check=False)
        finally:
            close_old_connections()

    def _round(self, *, include_startup_check: bool):
        """执行一轮恢复；返回 counts dict，失败（已记日志）返回 None。"""
        close_old_connections()
        try:
            from .tasks import recover_incomplete_tasks

            recovery = self._recovery_fn or (
                lambda queue_names: recover_incomplete_tasks(queue_names=queue_names)
            )
            counts = recovery(self.queue_names)
            logger.info("Task recovery round completed: %s", counts)
            result = counts
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("Task recovery round skipped: %s", exc)
            result = None
        except Exception as exc:
            logger.warning("Task recovery round failed: %s: %s", type(exc).__name__, exc)
            result = None
        finally:
            close_old_connections()
        if include_startup_check:
            self._startup_reindex_check()
        return result

    def _startup_reindex_check(self):
        if not self.include_startup_reindex_check:
            return
        # 启动时若向量索引处于 needs_rebuild（如维度迁移后）且无在途重建任务，
        # 自动入队一个；只在初始化执行，周期轮次不重复触发。
        close_old_connections()
        try:
            from .search import ensure_rebuild_task_enqueued

            if self._startup_check_fn is not None:
                self._startup_check_fn()
            else:
                ensure_rebuild_task_enqueued(reason="startup_reindex_check")
        except (OperationalError, ProgrammingError) as exc:
            logger.warning("Startup vector reindex check skipped: %s", exc)
        except Exception:
            logger.exception("Startup vector reindex check failed")
        finally:
            close_old_connections()


def _same_contract(loop: "TaskRecoveryLoop", kwargs: dict) -> bool:
    queue_names = kwargs.get("queue_names")
    incoming_queue = None if queue_names is None else tuple(str(name) for name in queue_names)
    incoming_contract = (incoming_queue, bool(kwargs.get("include_startup_reindex_check", True)))
    return loop.contract == incoming_contract


def start_recovery_loop(**kwargs) -> TaskRecoveryLoop:
    """进程级幂等启动：同契约的存活 loop 直接返回，不新建线程。

    - 存活且同契约 → 幂等复用。
    - 存活但 queue/启动检查契约不同 → RuntimeError，绝不静默换契约。
    - 正在停止且线程仍活着（join 超时后的窗口）→ RuntimeError：不能把
      stopping 实例当正常运行实例返回，也不能开第二个线程。
    - 旧线程已死 → 安全替换。
    """
    global _loop_instance
    with _loop_lock:
        loop = _loop_instance
        if loop is not None and loop.is_alive():
            if loop._stopping:
                raise RuntimeError(
                    "previous task recovery loop is still stopping; "
                    "retry start once its thread has exited"
                )
            if not _same_contract(loop, kwargs):
                raise RuntimeError(
                    f"live task recovery loop has a different contract: "
                    f"{loop.contract} requested {(kwargs.get('queue_names'), kwargs.get('include_startup_reindex_check', True))}"
                )
            return loop
        loop = TaskRecoveryLoop(**kwargs)
        loop.start()
        _loop_instance = loop
        _register_atexit_stop()
        return loop


def stop_recovery_loop(timeout: float = STOP_JOIN_TIMEOUT_SECONDS) -> bool:
    """停掉当前进程的 loop；join 成功才清除单例，超时则保留 stopping 状态。"""
    global _loop_instance
    with _loop_lock:
        loop = _loop_instance
    if loop is None:
        return True
    stopped = loop.stop(timeout=timeout)
    if stopped:
        with _loop_lock:
            if _loop_instance is loop:
                _loop_instance = None
    return stopped


def _stop_loop_at_exit():
    # 解释器退出的兜底停机：join 有限时间。若恢复轮阻塞在卡死回调上，
    # join 超时到期后即放行退出，daemon 线程随进程硬终止——atexit 绝不
    # 无限阻塞 shutdown；这是有界停止的已知限制。
    try:
        stop_recovery_loop(timeout=STOP_JOIN_TIMEOUT_SECONDS)
    except Exception:
        pass


def _register_atexit_stop():
    global _atexit_stop_registered
    if not _atexit_stop_registered:
        atexit.register(_stop_loop_at_exit)
        _atexit_stop_registered = True


def current_recovery_loop() -> "TaskRecoveryLoop | None":
    return _loop_instance


def run_recovery_round(queue_names=None):
    """执行一次有界恢复轮次（worker ``--once`` 的确定性恢复步骤）。

    与 loop 周期轮相同的连接卫生与错误处理：失败只记简短日志，不向
    调用方抛出。返回本轮 counts，失败返回 None。
    """
    loop = TaskRecoveryLoop(
        include_startup_reindex_check=False,
        queue_names=queue_names,
    )
    return loop._round(include_startup_check=False)
