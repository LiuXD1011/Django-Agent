// Business schema extracted from the approved working-tree baseline. No Django runtime dependency.
import type { TableDefinition } from "./schema-types.js";

export const tableDefinitions: TableDefinition[] = [
  {
    "name": "tenants",
    "columns": [
      {
        "name": "id",
        "type": "integer",
        "nullable": false,
        "primary": true,
        "auto": true,
        "unique": false,
        "encrypted": false
      },
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "description",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "space_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "legacy",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "personal_owner_id",
        "nullable": true,
        "primary": false,
        "unique": false,
        "on_delete": "RESTRICT",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "users",
          "column": "id"
        }
      },
      {
        "name": "api_key",
        "nullable": false,
        "primary": false,
        "unique": true,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "retriever_engines",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "active",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "business",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "default",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "storage_quota",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 10737418240,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "storage_used",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "model_thinking_config",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "agent_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "context_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "conversation_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "web_search_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": true
      },
      {
        "name": "parser_engine_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": true
      },
      {
        "name": "storage_engine_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": true
      },
      {
        "name": "credentials",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": true
      },
      {
        "name": "chat_history_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "retrieval_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      }
    ]
  },
  {
    "name": "users",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "username",
        "nullable": false,
        "primary": false,
        "unique": true,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "email",
        "nullable": false,
        "primary": false,
        "unique": true,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "password_hash",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "avatar",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": true,
        "primary": false,
        "unique": false,
        "on_delete": "SET NULL",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "is_active",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": true,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "can_access_all_tenants",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "is_system_admin",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "preferences",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      }
    ]
  },
  {
    "name": "auth_tokens",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "user_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "users",
          "column": "id"
        }
      },
      {
        "name": "token",
        "nullable": false,
        "primary": false,
        "unique": true,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "token_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "expires_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "is_revoked",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      }
    ]
  },
  {
    "name": "tenant_members",
    "columns": [
      {
        "name": "id",
        "type": "integer",
        "nullable": false,
        "primary": true,
        "auto": true,
        "unique": false,
        "encrypted": false
      },
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "user_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "users",
          "column": "id"
        }
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "role",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "owner",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "active",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "invited_by",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "joined_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "models",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "display_name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "source",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "description",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "parameters",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": true
      },
      {
        "name": "context_window",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "is_default",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "is_builtin",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "managed_by",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "fallback_priority",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "active",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "model_usage",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": true,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "model_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "model_name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "model_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "provider",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "scenario",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "request_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "success",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": true,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "request_count",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 1,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "prompt_tokens",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "completion_tokens",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "total_tokens",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "cached_tokens",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "reasoning_tokens",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "duration_ms",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "error_message",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "metadata",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      }
    ]
  },
  {
    "name": "knowledge_bases",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "description",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "document",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "chunking_config",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "image_processing_config",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "embedding_model_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "summary_model_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "cos_config",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "storage_provider_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "vlm_config",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "asr_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "extract_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "faq_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "question_generation_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "wiki_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "indexing_strategy",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "is_temporary",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "is_pinned",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "pinned_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "vector_store_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "creator_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "knowledges",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "knowledge_base_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "knowledge_bases",
          "column": "id"
        }
      },
      {
        "name": "type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "title",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "description",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "source",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "parse_status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "pending",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "enable_status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "enabled",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "embedding_model_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "file_name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "file_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "file_size",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "file_path",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "file_hash",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "storage_size",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "metadata",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "tag_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "summary_status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "none",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "pending_subtasks_count",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "last_faq_import_result",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "channel",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "web",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "processed_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "error_message",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "knowledge_images",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "knowledge_base_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "knowledge_bases",
          "column": "id"
        }
      },
      {
        "name": "knowledge_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "knowledges",
          "column": "id"
        }
      },
      {
        "name": "content_hash",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "storage_path",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "storage_owned",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": true,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "mime_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "application/octet-stream",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "width",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "height",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "source_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "source_ref",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "page_index",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "block_index",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "pending",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "ocr_text",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "caption",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "error_message",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "metadata",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      }
    ]
  },
  {
    "name": "chunks",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "knowledge_base_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "knowledge_bases",
          "column": "id"
        }
      },
      {
        "name": "knowledge_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "knowledges",
          "column": "id"
        }
      },
      {
        "name": "content",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "chunk_index",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "is_enabled",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": true,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "start_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "end_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "pre_chunk_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "next_chunk_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "chunk_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "text",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "context_header",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "context_parent_id",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "media_parent_id",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "anchor_chunk_id",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "chunking_version",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "image_info",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "relation_chunks",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "indirect_relation_chunks",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "metadata",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "tag_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "content_hash",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "flags",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 1,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "seq_id",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "integer",
        "encrypted": false
      }
    ]
  },
  {
    "name": "semantic_chunk_cache",
    "columns": [
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "auto": true,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "content_hash",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "model_signature",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "algorithm_version",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "window_size",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "percentile",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "real",
        "encrypted": false
      },
      {
        "name": "window_inputs",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "vectors",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "stream_states",
    "columns": [
      {
        "name": "message_id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "session_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "is_complete",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "is_error",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "error_message",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "final_content",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "final_refs",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "final_steps",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "final_duration_ms",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "stream_events",
    "columns": [
      {
        "name": "id",
        "type": "integer",
        "nullable": false,
        "primary": true,
        "auto": true,
        "unique": false,
        "encrypted": false
      },
      {
        "name": "message_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "session_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "event_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "data",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "offset",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "sessions",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "title",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "description",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "knowledge_base_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "max_rounds",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 5,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "enable_rewrite",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": true,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "fallback_strategy",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "fixed",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "fallback_response",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "很抱歉，我暂时无法回答这个问题。",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "keyword_threshold",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0.5,
        "type": "real",
        "encrypted": false
      },
      {
        "name": "vector_threshold",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0.5,
        "type": "real",
        "encrypted": false
      },
      {
        "name": "rerank_model_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "embedding_top_k",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 10,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "rerank_top_k",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 10,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "rerank_threshold",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0.65,
        "type": "real",
        "encrypted": false
      },
      {
        "name": "summary_model_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "summary_parameters",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "agent_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "context_config",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "agent_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "user_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "is_pinned",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "pinned_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "event_seq",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      }
    ]
  },
  {
    "name": "session_events",
    "columns": [
      {
        "name": "id",
        "type": "integer",
        "nullable": false,
        "primary": true,
        "auto": true,
        "unique": false,
        "encrypted": false
      },
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "session_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "sessions",
          "column": "id"
        }
      },
      {
        "name": "seq",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "request_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "data",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      }
    ]
  },
  {
    "name": "context_snapshots",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "session_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "sessions",
          "column": "id"
        }
      },
      {
        "name": "mode",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "boundary_message_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "boundary_created_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "content",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "key_info",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "summary",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "token_before",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "token_after",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "source_message_count",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "is_active",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": true,
        "type": "boolean",
        "encrypted": false
      }
    ]
  },
  {
    "name": "messages",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "request_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "session_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "sessions",
          "column": "id"
        }
      },
      {
        "name": "role",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "content",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "rendered_content",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "knowledge_references",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "agent_steps",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "mentioned_items",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "images",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "attachments",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "is_completed",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "is_fallback",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "channel",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "agent_duration_ms",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "knowledge_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "agent_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "main",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "visible_to_user",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": true,
        "type": "boolean",
        "encrypted": false
      }
    ]
  },
  {
    "name": "agent_actors",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "session_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "sessions",
          "column": "id"
        }
      },
      {
        "name": "parent_actor_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "actor_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "agent_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "mode",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "subagent",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "pending",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "last_outcome",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "background",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": false,
        "type": "boolean",
        "encrypted": false
      },
      {
        "name": "tool_whitelist",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "input_prompt",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "output",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "error",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "parent_message_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "started_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "completed_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "metadata",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      }
    ]
  },
  {
    "name": "knowledge_tags",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "knowledge_base_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "knowledge_bases",
          "column": "id"
        }
      },
      {
        "name": "name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "color",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "sort_order",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "seq_id",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "integer",
        "encrypted": false
      }
    ]
  },
  {
    "name": "generic_resources",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": true,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "resource_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "data",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": true
      },
      {
        "name": "status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "active",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "audit_logs",
    "columns": [
      {
        "name": "id",
        "type": "integer",
        "nullable": false,
        "primary": true,
        "auto": true,
        "unique": false,
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "actor_user_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "actor_role",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "action",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "target_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "target_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "target_user_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "request_path",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "request_method",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "outcome",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "success",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "details",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "task_records",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "task_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "pending",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "progress",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "real",
        "encrypted": false
      },
      {
        "name": "payload",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "result",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "json",
        "encrypted": false
      },
      {
        "name": "error_message",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "queue_name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "default",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "lease_expires_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "attempt_count",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "cancel_requested_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "claimed_by",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "model_rate_limit_state",
    "columns": [
      {
        "name": "key",
        "nullable": false,
        "primary": true,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "provider",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "model_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "available_tokens",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "real",
        "encrypted": false
      },
      {
        "name": "capacity",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "real",
        "encrypted": false
      },
      {
        "name": "refill_per_second",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "real",
        "encrypted": false
      },
      {
        "name": "last_refill_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "blocked_until",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "wiki_pages",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "knowledge_base_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "knowledge_bases",
          "column": "id"
        }
      },
      {
        "name": "slug",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "title",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "content",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "summary",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "source_refs",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "chunk_refs",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "aliases",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "in_links",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "out_links",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "page_metadata",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "page_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "page",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "published",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "folder_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "parent_slug",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "category_path",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "wiki_path",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "depth",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "sort_order",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "version",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 1,
        "type": "integer",
        "encrypted": false
      }
    ]
  },
  {
    "name": "wiki_folders",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "knowledge_base_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "knowledge_bases",
          "column": "id"
        }
      },
      {
        "name": "name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "parent_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "path",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "depth",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "sort_order",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      }
    ]
  },
  {
    "name": "wiki_pending_ops",
    "columns": [
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "auto": true,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "task_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "wiki:ingest",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "scope",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "knowledge_base",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "scope_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "op",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "dedup_key",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "payload",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "fail_count",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "error_message",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "enqueued_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "claimed_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "wiki_log_entries",
    "columns": [
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "tenant_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "integer",
        "encrypted": false,
        "reference": {
          "table": "tenants",
          "column": "id"
        }
      },
      {
        "name": "knowledge_base_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "knowledge_bases",
          "column": "id"
        }
      },
      {
        "name": "knowledge_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "action",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "doc_title",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "summary",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "pages_affected",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": [],
        "type": "json",
        "encrypted": false
      },
      {
        "name": "details",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "knowledge_processing_spans",
    "columns": [
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "auto": true,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "knowledge_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "knowledges",
          "column": "id"
        }
      },
      {
        "name": "attempt",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 1,
        "type": "integer",
        "encrypted": false
      },
      {
        "name": "span_id",
        "nullable": false,
        "primary": false,
        "unique": true,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "parent_span_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "kind",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "stage",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "status",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "pending",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "input_data",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "output_data",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "metadata",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": false
      },
      {
        "name": "error_code",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "error_message",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "error_detail",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "started_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "finished_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "duration_ms",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": 0,
        "type": "integer",
        "encrypted": false
      }
    ]
  },
  {
    "name": "integration_configs",
    "columns": [
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "updated_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "deleted_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "name",
        "nullable": false,
        "primary": true,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "parameters",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": {},
        "type": "json",
        "encrypted": true
      }
    ]
  },
  {
    "name": "device_sessions",
    "columns": [
      {
        "name": "id",
        "nullable": false,
        "primary": true,
        "unique": false,
        "factory": "uuid",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "user_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "users",
          "column": "id"
        }
      },
      {
        "name": "name",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "网页设备",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "client_type",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "web",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "access_digest",
        "nullable": false,
        "primary": false,
        "unique": true,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "access_expires_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "idle_expires_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "absolute_expires_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "last_seen_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "revoked_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "revoke_reason",
        "nullable": false,
        "primary": false,
        "unique": false,
        "defaultValue": "",
        "type": "text",
        "encrypted": false
      }
    ]
  },
  {
    "name": "device_refresh_tokens",
    "columns": [
      {
        "name": "digest",
        "nullable": false,
        "primary": true,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "session_id",
        "nullable": false,
        "primary": false,
        "unique": false,
        "on_delete": "CASCADE",
        "type": "text",
        "encrypted": false,
        "reference": {
          "table": "device_sessions",
          "column": "id"
        }
      },
      {
        "name": "created_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "factory": "now",
        "type": "text",
        "encrypted": false
      },
      {
        "name": "expires_at",
        "nullable": false,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      },
      {
        "name": "consumed_at",
        "nullable": true,
        "primary": false,
        "unique": false,
        "type": "text",
        "encrypted": false
      }
    ]
  }
];
