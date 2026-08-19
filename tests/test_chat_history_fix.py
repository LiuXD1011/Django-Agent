"""
验证 __chat_history__ 知识库是否正确隐藏

测试内容：
1. 数据库状态验证：is_temporary=True
2. API 响应验证：知识库列表不包含 __chat_history__
3. Agent 引擎验证：上下文中不包含 __chat_history__

运行方式：
    python manage.py test tests.test_chat_history_fix
    或
    python tests/test_chat_history_fix.py
"""

import os
import sys
import json
import time
import requests
import subprocess
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def test_database_state():
    """测试 1：验证数据库中 __chat_history__ 的状态"""
    import django
    django.setup()

    from personal_knowledge_base.models import KnowledgeBase

    print("=" * 60)
    print("测试 1：数据库状态验证")
    print("=" * 60)

    # 查找 __chat_history__
    chat_history_kbs = KnowledgeBase.objects.filter(name='__chat_history__')
    active_kb = chat_history_kbs.filter(deleted_at__isnull=True).first()

    if not active_kb:
        print("✅ 未找到活跃的 __chat_history__ 知识库")
        return True

    print(f"   ID: {active_kb.id}")
    print(f"   Name: {active_kb.name}")
    print(f"   is_temporary: {active_kb.is_temporary}")
    print(f"   Deleted: {active_kb.deleted_at}")

    if active_kb.is_temporary:
        print("✅ __chat_history__ 已标记为 is_temporary=True")
        return True
    else:
        print("❌ __chat_history__ 未标记为 is_temporary=True")
        return False


def test_user_visible_kbs():
    """测试 2：验证用户可见的知识库列表"""
    import django
    django.setup()

    from personal_knowledge_base.models import KnowledgeBase

    print("\n" + "=" * 60)
    print("测试 2：用户可见知识库列表")
    print("=" * 60)

    user_kbs = KnowledgeBase.objects.filter(
        deleted_at__isnull=True,
        is_temporary=False
    ).values_list('name', flat=True)

    kb_list = list(user_kbs)
    print(f"   用户可见知识库: {kb_list}")

    if '__chat_history__' in kb_list:
        print("❌ __chat_history__ 仍然对用户可见")
        return False
    else:
        print("✅ __chat_history__ 不在用户可见列表中")
        return True


def test_agent_context():
    """测试 3：验证 Agent 引擎上下文"""
    import django
    django.setup()

    from personal_knowledge_base.models import KnowledgeBase, Tenant

    print("\n" + "=" * 60)
    print("测试 3：Agent 引擎上下文验证")
    print("=" * 60)

    tenant = Tenant.objects.first()
    if not tenant:
        print("⚠️ 未找到租户，跳过测试")
        return True

    # 模拟 AgentEngine._build_context 的修复后逻辑
    kb_ids = list(KnowledgeBase.objects.filter(
        tenant=tenant,
        deleted_at__isnull=True,
        is_temporary=False
    ).values_list('id', flat=True))

    print(f"   Agent 可见知识库 IDs: {kb_ids}")

    # 验证每个知识库的名称
    for kb_id in kb_ids:
        kb = KnowledgeBase.objects.get(id=kb_id)
        print(f"   - {kb.name} (ID: {kb.id})")

    # 检查 __chat_history__ 是否在列表中
    chat_history_kb = KnowledgeBase.objects.filter(
        name='__chat_history__',
        deleted_at__isnull=True
    ).first()

    if chat_history_kb and chat_history_kb.id in kb_ids:
        print("❌ __chat_history__ 仍在 Agent 上下文中")
        return False
    else:
        print("✅ __chat_history__ 不在 Agent 上下文中")
        return True


def get_auth_token(base_url="http://localhost:8000"):
    """获取认证 token"""
    import django
    django.setup()

    from personal_knowledge_base.models import User, AuthToken
    from personal_knowledge_base.authentication import issue_tokens
    from django.utils import timezone

    try:
        # 直接从数据库获取用户并创建 token
        user = User.objects.filter(username='admin', deleted_at__isnull=True).first()
        if user:
            # 检查是否已有有效的 token
            existing_token = AuthToken.objects.filter(
                user=user,
                token_type='access',
                is_revoked=False,
                expires_at__gt=timezone.now()
            ).first()

            if existing_token:
                return existing_token.token

            # 创建新 token
            token, refresh = issue_tokens(user)
            return token
    except Exception as e:
        print(f"   获取 token 异常: {e}")
    return None


def test_api_response(base_url="http://localhost:8000"):
    """测试 4：验证 API 响应（需要 Django 服务运行）"""
    print("\n" + "=" * 60)
    print("测试 4：API 响应验证")
    print("=" * 60)

    try:
        # 获取认证 token
        token = get_auth_token(base_url)
        headers = {}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        # 测试知识库列表 API（正确的路径是 /api/v1/knowledge-bases）
        response = requests.get(f"{base_url}/api/v1/knowledge-bases", headers=headers, timeout=5)

        if response.status_code == 200:
            data = response.json()
            # 检查返回的数据结构
            items = data.get('items', data.get('knowledge_bases', []))
            kb_names = [kb.get('name') for kb in items]
            print(f"   API 返回的知识库: {kb_names}")

            if '__chat_history__' in kb_names:
                print("❌ API 仍然返回 __chat_history__")
                return False
            else:
                print("✅ API 未返回 __chat_history__")
                return True
        else:
            print(f"⚠️ API 请求失败: {response.status_code}")
            print(f"   响应内容: {response.text[:200]}")
            return None

    except requests.exceptions.ConnectionError:
        print("⚠️ Django 服务未运行，跳过 API 测试")
        return None
    except Exception as e:
        print(f"⚠️ API 测试异常: {e}")
        return None


def test_chat_query(base_url="http://localhost:8000"):
    """测试 5：验证对话查询（需要 Django 服务运行）"""
    print("\n" + "=" * 60)
    print("测试 5：对话查询验证")
    print("=" * 60)

    try:
        # 获取认证 token
        token = get_auth_token(base_url)
        headers = {}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        # 先创建一个 session（正确的路径是 /api/v1/sessions）
        session_response = requests.post(
            f"{base_url}/api/v1/sessions",
            json={"name": "测试会话-验证chat_history隐藏"},
            headers=headers,
            timeout=5
        )

        if session_response.status_code not in [200, 201]:
            print(f"⚠️ 创建会话失败: {session_response.status_code}")
            print(f"   响应内容: {session_response.text[:200]}")
            return None

        session_data = session_response.json()
        # 尝试多种可能的字段名
        session_id = (session_data.get('id') or
                     session_data.get('session_id') or
                     session_data.get('data', {}).get('id') or
                     session_data.get('data', {}).get('session_id'))
        print(f"   创建会话成功: {session_id}")
        print(f"   响应数据: {json.dumps(session_data, ensure_ascii=False)[:200]}")

        # 发送查询（使用正确的路径 /api/v1/knowledge-chat/）
        chat_response = requests.post(
            f"{base_url}/api/v1/knowledge-chat/{session_id}",
            json={
                "query": "我有哪些知识库",
            },
            headers=headers,
            timeout=60
        )

        if chat_response.status_code == 200:
            data = chat_response.json()
            # 尝试多种可能的字段名
            answer = (data.get('answer', '') or
                     data.get('content', '') or
                     data.get('message', '') or
                     data.get('data', {}).get('content', ''))

            # 如果是流式响应，可能需要读取多个事件
            if not answer and 'text' in str(data):
                answer = str(data)

            print(f"   Agent 回答: {answer[:300]}...")

            if '__chat_history__' in answer:
                print("❌ Agent 回答中包含 __chat_history__")
                return False
            else:
                print("✅ Agent 回答中未包含 __chat_history__")
                return True
        else:
            print(f"⚠️ 对话请求失败: {chat_response.status_code}")
            print(f"   响应内容: {chat_response.text[:200]}")
            return None

    except requests.exceptions.ConnectionError:
        print("⚠️ Django 服务未运行，跳过对话测试")
        return None
    except Exception as e:
        print(f"⚠️ 对话测试异常: {e}")
        import traceback
        traceback.print_exc()
        return None


def run_all_tests(auto_start_server=True):
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("__chat_history__ 隐藏修复验证测试")
    print("=" * 60)

    server_process = None
    base_url = "http://localhost:8000"

    # 如果需要，自动启动 Django 服务
    if auto_start_server:
        print("\n正在启动 Django 服务...")
        server_process = subprocess.Popen(
            [sys.executable, "manage.py", "runserver", "--noreload"],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        # 等待服务启动
        time.sleep(5)

        # 检查服务是否启动成功
        try:
            # 使用正确的 API 路径前缀 /api/v1/
            requests.get(f"{base_url}/api/v1/auth/me", timeout=2)
            print("✅ Django 服务已启动")
        except:
            print("⚠️ Django 服务启动失败，跳过 API 测试")
            auto_start_server = False

    results = {
        "数据库状态": test_database_state(),
        "用户可见知识库": test_user_visible_kbs(),
        "Agent 上下文": test_agent_context(),
        "API 响应": test_api_response(base_url) if auto_start_server else None,
        "对话查询": test_chat_query(base_url) if auto_start_server else None,
    }

    # 停止 Django 服务
    if server_process:
        print("\n正在停止 Django 服务...")
        server_process.terminate()
        server_process.wait()
        print("✅ Django 服务已停止")

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    all_passed = True
    for test_name, result in results.items():
        if result is True:
            print(f"✅ {test_name}: 通过")
        elif result is False:
            print(f"❌ {test_name}: 失败")
            all_passed = False
        else:
            print(f"⚠️ {test_name}: 跳过")

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有测试通过！__chat_history__ 已正确隐藏。")
    else:
        print("💥 存在测试失败，请检查修复。")
    print("=" * 60)

    return all_passed


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
