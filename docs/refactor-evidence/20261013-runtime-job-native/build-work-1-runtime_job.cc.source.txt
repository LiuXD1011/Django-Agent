// Trusted desktop main/bootstrap only. No PID-based termination is exported.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <delayimp.h>
#include <node_api.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>

// Node's import library names node.exe. Electron exports the same stable
// Node-API from its own image. Resolve only that delayed import to this host.
static FARPROC WINAPI HostImport(unsigned int event, DelayLoadInfo* info) {
  if (event != dliNotePreLoadLibrary || _stricmp(info->szDll, "node.exe") != 0) return nullptr;
  return reinterpret_cast<FARPROC>(GetModuleHandleW(nullptr));
}
extern "C" const PfnDliHook __pfnDliNotifyHook2 = HostImport;

namespace {
struct Failure : std::runtime_error {
  const char* code;
  Failure(const char* code, const std::string& message) : std::runtime_error(message), code(code) {}
};
void WinCheck(BOOL result, const char* operation) {
  if (!result) throw Failure("ERR_RUNTIME_JOB_WIN32", std::string(operation) + " failed (Win32 " + std::to_string(GetLastError()) + ")");
}
void NapiCheck(napi_status result) {
  if (result != napi_ok) throw Failure("ERR_RUNTIME_JOB_NAPI", "Runtime Job Node-API operation failed");
}
template <napi_value (*Callback)(napi_env, napi_callback_info)>
napi_value Guard(napi_env env, napi_callback_info info) {
  try { return Callback(env, info); }
  catch (const Failure& error) { napi_throw_error(env, error.code, error.what()); }
  catch (const std::exception&) { napi_throw_error(env, "ERR_RUNTIME_JOB_NATIVE", "Runtime Job native allocation failed"); }
  catch (...) { napi_throw_error(env, "ERR_RUNTIME_JOB_NATIVE", "Runtime Job native operation failed"); }
  return nullptr;
}
struct Handle {
  HANDLE value = nullptr;
  explicit Handle(HANDLE value = nullptr) : value(value) {}
  ~Handle() { if (value) CloseHandle(value); }
  Handle(const Handle&) = delete;
  Handle& operator=(const Handle&) = delete;
  HANDLE Release() { HANDLE result = value; value = nullptr; return result; }
};
struct Lifetime {
  HANDLE job;
  HANDLE root;
  Lifetime(HANDLE job, HANDLE root) : job(job), root(root) {}
  ~Lifetime() {
    if (job) CloseHandle(job);  // Last Job handle closes => kill only this tree.
    if (root) CloseHandle(root);
  }
};
constexpr napi_type_tag LifetimeTag = {0x86cd055a7eff45f9ULL, 0xa18418a471f9a03dULL};

uint64_t CreatedAt(HANDLE process) {
  FILETIME created{}, exited{}, kernel{}, user{};
  WinCheck(GetProcessTimes(process, &created, &exited, &kernel, &user), "GetProcessTimes");
  return (static_cast<uint64_t>(created.dwHighDateTime) << 32) | created.dwLowDateTime;
}
std::wstring Image(HANDLE process) {
  std::wstring image(32768, L'\0');
  DWORD length = static_cast<DWORD>(image.size());
  WinCheck(QueryFullProcessImageNameW(process, 0, image.data(), &length), "QueryFullProcessImageNameW");
  image.resize(length);
  return image;
}
DWORD Wait(HANDLE process) {
  DWORD result = WaitForSingleObject(process, 0);
  if (result != WAIT_OBJECT_0 && result != WAIT_TIMEOUT) {
    throw Failure("ERR_RUNTIME_JOB_WIN32", "WaitForSingleObject failed (Win32 " + std::to_string(GetLastError()) + ")");
  }
  return result;
}
std::wstring String(napi_env env, napi_value value) {
  napi_valuetype type;
  NapiCheck(napi_typeof(env, value, &type));
  if (type != napi_string) throw Failure("ERR_RUNTIME_JOB_ARGUMENT", "Expected a string");
  size_t length = 0;
  NapiCheck(napi_get_value_string_utf16(env, value, nullptr, 0, &length));
  if (length == 0 || length > 32768) throw Failure("ERR_RUNTIME_JOB_ARGUMENT", "Invalid string length");
  std::wstring result(length + 1, L'\0');
  static_assert(sizeof(wchar_t) == sizeof(char16_t), "Windows UTF-16 is required");
  NapiCheck(napi_get_value_string_utf16(env, value, reinterpret_cast<char16_t*>(result.data()), result.size(), &length));
  result.resize(length);
  if (result.find(L'\0') != std::wstring::npos) throw Failure("ERR_RUNTIME_JOB_ARGUMENT", "NUL is not permitted");
  return result;
}
uint64_t Decimal(const std::wstring& value) {
  if (value.empty() || value[0] == L'0') throw Failure("ERR_RUNTIME_JOB_ARGUMENT", "Expected canonical positive FILETIME");
  uint64_t number = 0;
  for (wchar_t digit : value) {
    if (digit < L'0' || digit > L'9' || number > (std::numeric_limits<uint64_t>::max() - (digit - L'0')) / 10) {
      throw Failure("ERR_RUNTIME_JOB_ARGUMENT", "Invalid unsigned FILETIME");
    }
    number = number * 10 + (digit - L'0');
  }
  return number;
}
bool SameImage(std::wstring actual, std::wstring expected) {
  std::replace(actual.begin(), actual.end(), L'/', L'\\');
  std::replace(expected.begin(), expected.end(), L'/', L'\\');
  return CompareStringOrdinal(actual.data(), static_cast<int>(actual.size()), expected.data(), static_cast<int>(expected.size()), TRUE) == CSTR_EQUAL;
}
napi_value Number(napi_env env, DWORD value) {
  napi_value result; NapiCheck(napi_create_uint32(env, value, &result)); return result;
}
napi_value Boolean(napi_env env, bool value) {
  napi_value result; NapiCheck(napi_get_boolean(env, value, &result)); return result;
}
napi_value Undefined(napi_env env) {
  napi_value result; NapiCheck(napi_get_undefined(env, &result)); return result;
}
void Property(napi_env env, napi_value object, const char* name, napi_value value) {
  NapiCheck(napi_set_named_property(env, object, name, value));
}
void Finalize(napi_env, void* data, void*) { delete static_cast<Lifetime*>(data); }
Lifetime* Receiver(napi_env env, napi_callback_info info, bool allowClosed = false) {
  size_t argc = 0;
  napi_value receiver;
  NapiCheck(napi_get_cb_info(env, info, &argc, nullptr, &receiver, nullptr));
  bool tagged = false;
  napi_valuetype type;
  NapiCheck(napi_typeof(env, receiver, &type));
  if (type == napi_object) NapiCheck(napi_check_object_type_tag(env, receiver, &LifetimeTag, &tagged));
  if (!tagged) throw Failure("ERR_JOB_RECEIVER", "Expected the original Runtime Job object");
  void* data = nullptr;
  NapiCheck(napi_unwrap(env, receiver, &data));
  if (!data) throw Failure("ERR_JOB_RECEIVER", "Missing Runtime Job object");
  auto* lifetime = static_cast<Lifetime*>(data);
  if (!allowClosed && !lifetime->job) throw Failure("ERR_JOB_CLOSED", "Runtime Job is closed");
  return lifetime;
}
napi_value Status(napi_env env, napi_callback_info info) {
  auto* lifetime = Receiver(env, info);
  const bool exited = Wait(lifetime->root) == WAIT_OBJECT_0;
  DWORD exitCode = 0;
  if (exited) WinCheck(GetExitCodeProcess(lifetime->root, &exitCode), "GetExitCodeProcess");
  JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting{};
  WinCheck(QueryInformationJobObject(lifetime->job, JobObjectBasicAccountingInformation, &accounting, sizeof(accounting), nullptr), "QueryInformationJobObject");
  napi_value result, code;
  NapiCheck(napi_create_object(env, &result));
  if (exited) code = Number(env, exitCode); else NapiCheck(napi_get_null(env, &code));
  Property(env, result, "rootExited", Boolean(env, exited));
  Property(env, result, "rootExitCode", code);
  Property(env, result, "activeProcesses", Number(env, accounting.ActiveProcesses));
  return result;
}
napi_value Terminate(napi_env env, napi_callback_info info) {
  auto* lifetime = Receiver(env, info);
  WinCheck(TerminateJobObject(lifetime->job, 1), "TerminateJobObject");
  return Undefined(env);
}
napi_value Close(napi_env env, napi_callback_info info) {
  auto* lifetime = Receiver(env, info, true);
  if (lifetime->job) {
    WinCheck(CloseHandle(lifetime->job), "CloseHandle Job");
    lifetime->job = nullptr;
  }
  if (lifetime->root) {
    WinCheck(CloseHandle(lifetime->root), "CloseHandle root");
    lifetime->root = nullptr;
  }
  return Undefined(env);
}
napi_value CurrentIdentity(napi_env env, napi_callback_info) {
  HANDLE current = GetCurrentProcess();
  const auto createdAt = std::to_string(CreatedAt(current));
  const auto executable = Image(current);
  napi_value result, created, image;
  NapiCheck(napi_create_object(env, &result));
  NapiCheck(napi_create_string_utf8(env, createdAt.data(), createdAt.size(), &created));
  NapiCheck(napi_create_string_utf16(env, reinterpret_cast<const char16_t*>(executable.data()), executable.size(), &image));
  Property(env, result, "pid", Number(env, GetCurrentProcessId()));
  Property(env, result, "createdAt", created);
  Property(env, result, "executable", image);
  return result;
}
napi_value BindRoot(napi_env env, napi_callback_info info) {
  size_t argc = 4;
  napi_value args[4];
  NapiCheck(napi_get_cb_info(env, info, &argc, args, nullptr, nullptr));
  if (argc != 3) throw Failure("ERR_RUNTIME_JOB_ARGUMENT", "bindRoot requires pid, FILETIME and executable");
  napi_valuetype type;
  NapiCheck(napi_typeof(env, args[0], &type));
  double number = 0;
  if (type != napi_number) throw Failure("ERR_RUNTIME_JOB_ARGUMENT", "Expected numeric process ID");
  NapiCheck(napi_get_value_double(env, args[0], &number));
  if (!std::isfinite(number) || number < 1 || number > MAXDWORD || std::floor(number) != number || number == GetCurrentProcessId()) {
    throw Failure("ERR_RUNTIME_JOB_ARGUMENT", "Expected a different positive DWORD process ID");
  }
  const DWORD pid = static_cast<DWORD>(number);
  const uint64_t createdAt = Decimal(String(env, args[1]));
  const std::wstring expectedImage = String(env, args[2]);
  Handle root(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA | PROCESS_TERMINATE | SYNCHRONIZE, FALSE, pid));
  WinCheck(root.value != nullptr, "OpenProcess");
  // All observations and Assign use this SAME original process HANDLE. A late
  // queued ACK cannot authorize a new process that reused the numeric PID.
  if (GetProcessId(root.value) != pid || CreatedAt(root.value) != createdAt || Wait(root.value) != WAIT_TIMEOUT || !SameImage(Image(root.value), expectedImage)) {
    throw Failure("ERR_ROOT_IDENTITY", "Runtime root identity is not the live original child");
  }
  Handle job(CreateJobObjectW(nullptr, nullptr));
  WinCheck(job.value != nullptr, "CreateJobObjectW");
  JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
  limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
  WinCheck(SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits)), "SetInformationJobObject");
  if (Wait(root.value) != WAIT_TIMEOUT) throw Failure("ERR_ROOT_IDENTITY", "Runtime root exited before binding");
  WinCheck(AssignProcessToJobObject(job.value, root.value), "AssignProcessToJobObject");
  if (Wait(root.value) != WAIT_TIMEOUT) throw Failure("ERR_ROOT_IDENTITY", "Runtime root exited during binding");
  auto lifetime = std::make_unique<Lifetime>(job.value, root.value);
  job.Release();
  root.Release();
  napi_value result;
  NapiCheck(napi_create_object(env, &result));
  const napi_property_descriptor methods[] = {
    {"status", nullptr, Guard<Status>, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"terminate", nullptr, Guard<Terminate>, nullptr, nullptr, nullptr, napi_default, nullptr},
    {"close", nullptr, Guard<Close>, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  NapiCheck(napi_define_properties(env, result, 3, methods));
  NapiCheck(napi_type_tag_object(env, result, &LifetimeTag));
  NapiCheck(napi_wrap(env, result, lifetime.get(), Finalize, nullptr, nullptr));
  lifetime.release();
  return result;
}
}  // namespace

NAPI_MODULE_INIT() {
  try {
    const napi_property_descriptor methods[] = {
      {"currentIdentity", nullptr, Guard<CurrentIdentity>, nullptr, nullptr, nullptr, napi_default_jsproperty, nullptr},
      {"bindRoot", nullptr, Guard<BindRoot>, nullptr, nullptr, nullptr, napi_default_jsproperty, nullptr},
    };
    NapiCheck(napi_define_properties(env, exports, 2, methods));
    return exports;
  } catch (...) {
    napi_throw_error(env, "ERR_RUNTIME_JOB_NAPI", "Runtime Job initialization failed");
    return nullptr;
  }
}
