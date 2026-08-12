-- 2026-06-26: BASELINE schema reconcile (idempotent).
-- Backfill pentru tabelele/coloanele/indexurile create ad-hoc pe staging FARA migratie,
-- ca sa ajunga pe productie la release. Re-rulabil fara efect (IF NOT EXISTS + garzi).
-- Exclude: backup/temp (_bak), _release_migrations, si tabelele deja in alte migratii.
-- NU contine seed de date tranzactionale sau secrete.

CREATE TABLE IF NOT EXISTS public.admin_users (
    id bigint NOT NULL,
    username character varying(100) NOT NULL,
    email character varying(320) NOT NULL,
    password_hash character varying(255) NOT NULL,
    totp_secret character varying(64),
    role character varying(30) DEFAULT 'admin'::character varying,
    is_active boolean DEFAULT true,
    last_login_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane admin_users (drift; nullable, idempotent)
ALTER TABLE public.admin_users ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.admin_users ADD COLUMN IF NOT EXISTS username character varying(100);
ALTER TABLE public.admin_users ADD COLUMN IF NOT EXISTS email character varying(320);
ALTER TABLE public.admin_users ADD COLUMN IF NOT EXISTS password_hash character varying(255);
ALTER TABLE public.admin_users ADD COLUMN IF NOT EXISTS totp_secret character varying(64);
ALTER TABLE public.admin_users ADD COLUMN IF NOT EXISTS role character varying(30) DEFAULT 'admin'::character varying;
ALTER TABLE public.admin_users ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true;
ALTER TABLE public.admin_users ADD COLUMN IF NOT EXISTS last_login_at timestamp with time zone;
ALTER TABLE public.admin_users ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.admin_users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.admin_users_id_seq OWNED BY public.admin_users.id;

CREATE TABLE IF NOT EXISTS public.ai_autoreply_feedback (
    id bigint NOT NULL,
    email_id bigint,
    suggested_text text,
    decision character varying(12),
    reject_reason text,
    decided_by character varying(100),
    created_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane ai_autoreply_feedback (drift; nullable, idempotent)
ALTER TABLE public.ai_autoreply_feedback ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.ai_autoreply_feedback ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.ai_autoreply_feedback ADD COLUMN IF NOT EXISTS suggested_text text;
ALTER TABLE public.ai_autoreply_feedback ADD COLUMN IF NOT EXISTS decision character varying(12);
ALTER TABLE public.ai_autoreply_feedback ADD COLUMN IF NOT EXISTS reject_reason text;
ALTER TABLE public.ai_autoreply_feedback ADD COLUMN IF NOT EXISTS decided_by character varying(100);
ALTER TABLE public.ai_autoreply_feedback ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.ai_autoreply_feedback_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_autoreply_feedback_id_seq OWNED BY public.ai_autoreply_feedback.id;

CREATE TABLE IF NOT EXISTS public.ai_autoreply_prompt_versions (
    id bigint NOT NULL,
    prompt_text text,
    source character varying(20),
    explicatie text,
    based_on integer,
    created_by character varying(100),
    created_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane ai_autoreply_prompt_versions (drift; nullable, idempotent)
ALTER TABLE public.ai_autoreply_prompt_versions ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.ai_autoreply_prompt_versions ADD COLUMN IF NOT EXISTS prompt_text text;
ALTER TABLE public.ai_autoreply_prompt_versions ADD COLUMN IF NOT EXISTS source character varying(20);
ALTER TABLE public.ai_autoreply_prompt_versions ADD COLUMN IF NOT EXISTS explicatie text;
ALTER TABLE public.ai_autoreply_prompt_versions ADD COLUMN IF NOT EXISTS based_on integer;
ALTER TABLE public.ai_autoreply_prompt_versions ADD COLUMN IF NOT EXISTS created_by character varying(100);
ALTER TABLE public.ai_autoreply_prompt_versions ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.ai_autoreply_prompt_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_autoreply_prompt_versions_id_seq OWNED BY public.ai_autoreply_prompt_versions.id;

CREATE TABLE IF NOT EXISTS public.ai_call_log (
    id bigint NOT NULL,
    task character varying(120),
    model character varying(80),
    tokens_in integer,
    tokens_out integer,
    cost_usd numeric(12,6),
    ok boolean,
    error_code character varying(40),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    email_id bigint
);
-- reconcile coloane ai_call_log (drift; nullable, idempotent)
ALTER TABLE public.ai_call_log ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.ai_call_log ADD COLUMN IF NOT EXISTS task character varying(120);
ALTER TABLE public.ai_call_log ADD COLUMN IF NOT EXISTS model character varying(80);
ALTER TABLE public.ai_call_log ADD COLUMN IF NOT EXISTS tokens_in integer;
ALTER TABLE public.ai_call_log ADD COLUMN IF NOT EXISTS tokens_out integer;
ALTER TABLE public.ai_call_log ADD COLUMN IF NOT EXISTS cost_usd numeric(12,6);
ALTER TABLE public.ai_call_log ADD COLUMN IF NOT EXISTS ok boolean;
ALTER TABLE public.ai_call_log ADD COLUMN IF NOT EXISTS error_code character varying(40);
ALTER TABLE public.ai_call_log ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();
ALTER TABLE public.ai_call_log ADD COLUMN IF NOT EXISTS email_id bigint;

CREATE SEQUENCE IF NOT EXISTS public.ai_call_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_call_log_id_seq OWNED BY public.ai_call_log.id;

CREATE TABLE IF NOT EXISTS public.ai_category_corrections (
    id bigint NOT NULL,
    email_id bigint,
    old_category character varying(20),
    new_category character varying(20),
    old_reason text,
    corrected_by character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
-- reconcile coloane ai_category_corrections (drift; nullable, idempotent)
ALTER TABLE public.ai_category_corrections ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.ai_category_corrections ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.ai_category_corrections ADD COLUMN IF NOT EXISTS old_category character varying(20);
ALTER TABLE public.ai_category_corrections ADD COLUMN IF NOT EXISTS new_category character varying(20);
ALTER TABLE public.ai_category_corrections ADD COLUMN IF NOT EXISTS old_reason text;
ALTER TABLE public.ai_category_corrections ADD COLUMN IF NOT EXISTS corrected_by character varying(100);
ALTER TABLE public.ai_category_corrections ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.ai_category_corrections_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_category_corrections_id_seq OWNED BY public.ai_category_corrections.id;

CREATE TABLE IF NOT EXISTS public.ai_category_prompt_versions (
    id bigint NOT NULL,
    category character varying(20),
    prompt_text text,
    source character varying(20),
    explicatie text,
    based_on integer,
    created_by character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
-- reconcile coloane ai_category_prompt_versions (drift; nullable, idempotent)
ALTER TABLE public.ai_category_prompt_versions ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.ai_category_prompt_versions ADD COLUMN IF NOT EXISTS category character varying(20);
ALTER TABLE public.ai_category_prompt_versions ADD COLUMN IF NOT EXISTS prompt_text text;
ALTER TABLE public.ai_category_prompt_versions ADD COLUMN IF NOT EXISTS source character varying(20);
ALTER TABLE public.ai_category_prompt_versions ADD COLUMN IF NOT EXISTS explicatie text;
ALTER TABLE public.ai_category_prompt_versions ADD COLUMN IF NOT EXISTS based_on integer;
ALTER TABLE public.ai_category_prompt_versions ADD COLUMN IF NOT EXISTS created_by character varying(100);
ALTER TABLE public.ai_category_prompt_versions ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.ai_category_prompt_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_category_prompt_versions_id_seq OWNED BY public.ai_category_prompt_versions.id;

CREATE TABLE IF NOT EXISTS public.ai_category_prompts (
    category character varying(20) NOT NULL,
    prompt_text text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by character varying(100)
);
-- reconcile coloane ai_category_prompts (drift; nullable, idempotent)
ALTER TABLE public.ai_category_prompts ADD COLUMN IF NOT EXISTS category character varying(20);
ALTER TABLE public.ai_category_prompts ADD COLUMN IF NOT EXISTS prompt_text text;
ALTER TABLE public.ai_category_prompts ADD COLUMN IF NOT EXISTS updated_at timestamp with time zone DEFAULT now();
ALTER TABLE public.ai_category_prompts ADD COLUMN IF NOT EXISTS updated_by character varying(100);

CREATE TABLE IF NOT EXISTS public.ai_department_corrections (
    id integer NOT NULL,
    email_id bigint,
    old_department text,
    new_department text,
    old_reason text,
    corrected_by text,
    created_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane ai_department_corrections (drift; nullable, idempotent)
ALTER TABLE public.ai_department_corrections ADD COLUMN IF NOT EXISTS id integer;
ALTER TABLE public.ai_department_corrections ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.ai_department_corrections ADD COLUMN IF NOT EXISTS old_department text;
ALTER TABLE public.ai_department_corrections ADD COLUMN IF NOT EXISTS new_department text;
ALTER TABLE public.ai_department_corrections ADD COLUMN IF NOT EXISTS old_reason text;
ALTER TABLE public.ai_department_corrections ADD COLUMN IF NOT EXISTS corrected_by text;
ALTER TABLE public.ai_department_corrections ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.ai_department_corrections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_department_corrections_id_seq OWNED BY public.ai_department_corrections.id;

CREATE TABLE IF NOT EXISTS public.ai_department_prompt_versions (
    id integer NOT NULL,
    department text,
    prompt_text text,
    source text,
    explicatie text,
    based_on integer,
    created_by text,
    created_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane ai_department_prompt_versions (drift; nullable, idempotent)
ALTER TABLE public.ai_department_prompt_versions ADD COLUMN IF NOT EXISTS id integer;
ALTER TABLE public.ai_department_prompt_versions ADD COLUMN IF NOT EXISTS department text;
ALTER TABLE public.ai_department_prompt_versions ADD COLUMN IF NOT EXISTS prompt_text text;
ALTER TABLE public.ai_department_prompt_versions ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE public.ai_department_prompt_versions ADD COLUMN IF NOT EXISTS explicatie text;
ALTER TABLE public.ai_department_prompt_versions ADD COLUMN IF NOT EXISTS based_on integer;
ALTER TABLE public.ai_department_prompt_versions ADD COLUMN IF NOT EXISTS created_by text;
ALTER TABLE public.ai_department_prompt_versions ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.ai_department_prompt_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_department_prompt_versions_id_seq OWNED BY public.ai_department_prompt_versions.id;

CREATE TABLE IF NOT EXISTS public.ai_department_prompts (
    department text NOT NULL,
    prompt_text text,
    updated_at timestamp with time zone,
    updated_by text
);
-- reconcile coloane ai_department_prompts (drift; nullable, idempotent)
ALTER TABLE public.ai_department_prompts ADD COLUMN IF NOT EXISTS department text;
ALTER TABLE public.ai_department_prompts ADD COLUMN IF NOT EXISTS prompt_text text;
ALTER TABLE public.ai_department_prompts ADD COLUMN IF NOT EXISTS updated_at timestamp with time zone;
ALTER TABLE public.ai_department_prompts ADD COLUMN IF NOT EXISTS updated_by text;

CREATE TABLE IF NOT EXISTS public.ai_priority_corrections (
    id bigint NOT NULL,
    email_id bigint,
    old_priority character varying(8),
    new_priority character varying(8),
    old_reason text,
    corrected_by character varying(100),
    created_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane ai_priority_corrections (drift; nullable, idempotent)
ALTER TABLE public.ai_priority_corrections ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.ai_priority_corrections ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.ai_priority_corrections ADD COLUMN IF NOT EXISTS old_priority character varying(8);
ALTER TABLE public.ai_priority_corrections ADD COLUMN IF NOT EXISTS new_priority character varying(8);
ALTER TABLE public.ai_priority_corrections ADD COLUMN IF NOT EXISTS old_reason text;
ALTER TABLE public.ai_priority_corrections ADD COLUMN IF NOT EXISTS corrected_by character varying(100);
ALTER TABLE public.ai_priority_corrections ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.ai_priority_corrections_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_priority_corrections_id_seq OWNED BY public.ai_priority_corrections.id;

CREATE TABLE IF NOT EXISTS public.ai_priority_prompt_versions (
    id bigint NOT NULL,
    prompt_text text,
    source character varying(20),
    explicatie text,
    based_on integer,
    created_by character varying(100),
    created_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane ai_priority_prompt_versions (drift; nullable, idempotent)
ALTER TABLE public.ai_priority_prompt_versions ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.ai_priority_prompt_versions ADD COLUMN IF NOT EXISTS prompt_text text;
ALTER TABLE public.ai_priority_prompt_versions ADD COLUMN IF NOT EXISTS source character varying(20);
ALTER TABLE public.ai_priority_prompt_versions ADD COLUMN IF NOT EXISTS explicatie text;
ALTER TABLE public.ai_priority_prompt_versions ADD COLUMN IF NOT EXISTS based_on integer;
ALTER TABLE public.ai_priority_prompt_versions ADD COLUMN IF NOT EXISTS created_by character varying(100);
ALTER TABLE public.ai_priority_prompt_versions ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.ai_priority_prompt_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_priority_prompt_versions_id_seq OWNED BY public.ai_priority_prompt_versions.id;

CREATE TABLE IF NOT EXISTS public.ai_reports (
    id bigint NOT NULL,
    report_type character varying(64) NOT NULL,
    status character varying(24) DEFAULT 'completed'::character varying NOT NULL,
    params jsonb,
    result jsonb,
    email_count integer,
    group_count integer,
    ai_calls integer,
    generated_by character varying(160),
    generated_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    duration_ms integer,
    error text
);
-- reconcile coloane ai_reports (drift; nullable, idempotent)
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS report_type character varying(64);
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS status character varying(24) DEFAULT 'completed'::character varying;
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS params jsonb;
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS result jsonb;
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS email_count integer;
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS group_count integer;
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS ai_calls integer;
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS generated_by character varying(160);
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS generated_at timestamp with time zone DEFAULT now();
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS finished_at timestamp with time zone;
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS duration_ms integer;
ALTER TABLE public.ai_reports ADD COLUMN IF NOT EXISTS error text;

CREATE SEQUENCE IF NOT EXISTS public.ai_reports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ai_reports_id_seq OWNED BY public.ai_reports.id;

CREATE TABLE IF NOT EXISTS public.api_keys (
    id integer NOT NULL,
    label character varying(64) NOT NULL,
    key_hash character varying(128) NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane api_keys (drift; nullable, idempotent)
ALTER TABLE public.api_keys ADD COLUMN IF NOT EXISTS id integer;
ALTER TABLE public.api_keys ADD COLUMN IF NOT EXISTS label character varying(64);
ALTER TABLE public.api_keys ADD COLUMN IF NOT EXISTS key_hash character varying(128);
ALTER TABLE public.api_keys ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true;
ALTER TABLE public.api_keys ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.api_keys_id_seq OWNED BY public.api_keys.id;

CREATE TABLE IF NOT EXISTS public.attachments (
    id bigint NOT NULL,
    email_id bigint NOT NULL,
    graph_attachment_id character varying(255),
    name character varying(500),
    content_type character varying(200),
    size_bytes bigint,
    sha256 character varying(64),
    storage_path text,
    is_suspicious boolean DEFAULT false,
    suspicious_reasons jsonb,
    created_at timestamp with time zone DEFAULT now(),
    doc_discarded boolean DEFAULT false,
    doc_discard_reason text,
    doc_discarded_at timestamp with time zone,
    scan_verdict text,
    scan_threats jsonb,
    scanned_at timestamp with time zone,
    content_id text,
    is_inline boolean DEFAULT false NOT NULL
);
-- reconcile coloane attachments (drift; nullable, idempotent)
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS graph_attachment_id character varying(255);
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS name character varying(500);
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS content_type character varying(200);
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS size_bytes bigint;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS sha256 character varying(64);
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS storage_path text;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS is_suspicious boolean DEFAULT false;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS suspicious_reasons jsonb;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS doc_discarded boolean DEFAULT false;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS doc_discard_reason text;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS doc_discarded_at timestamp with time zone;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS scan_verdict text;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS scan_threats jsonb;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS scanned_at timestamp with time zone;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS content_id text;
ALTER TABLE public.attachments ADD COLUMN IF NOT EXISTS is_inline boolean DEFAULT false;

CREATE SEQUENCE IF NOT EXISTS public.attachments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.attachments_id_seq OWNED BY public.attachments.id;

CREATE TABLE IF NOT EXISTS public.audit_log (
    id bigint NOT NULL,
    actor character varying(100),
    action character varying(100) NOT NULL,
    entity_type character varying(50),
    entity_id bigint,
    details jsonb,
    ip_address inet,
    user_agent text,
    created_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane audit_log (drift; nullable, idempotent)
ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS actor character varying(100);
ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS action character varying(100);
ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS entity_type character varying(50);
ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS entity_id bigint;
ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS details jsonb;
ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS ip_address inet;
ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS user_agent text;
ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.audit_log_id_seq OWNED BY public.audit_log.id;

CREATE TABLE IF NOT EXISTS public.clients (
    id bigint NOT NULL,
    iris_client_id bigint,
    name character varying(500) NOT NULL,
    emails jsonb DEFAULT '[]'::jsonb NOT NULL,
    phones jsonb DEFAULT '[]'::jsonb NOT NULL,
    company_id integer,
    is_active boolean DEFAULT true,
    last_synced_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    satisfaction_pct numeric(5,2),
    email_priority smallint
);
-- reconcile coloane clients (drift; nullable, idempotent)
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS iris_client_id bigint;
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS name character varying(500);
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS emails jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS phones jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS company_id integer;
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true;
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS last_synced_at timestamp with time zone DEFAULT now();
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS updated_at timestamp with time zone DEFAULT now();
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS satisfaction_pct numeric(5,2);
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS email_priority smallint;

CREATE SEQUENCE IF NOT EXISTS public.clients_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.clients_id_seq OWNED BY public.clients.id;

CREATE TABLE IF NOT EXISTS public.cts_api_log (
    id bigint NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    action character varying(32) NOT NULL,
    email_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    requested integer DEFAULT 0 NOT NULL,
    success integer DEFAULT 0 NOT NULL,
    total integer DEFAULT 0 NOT NULL,
    http_status integer DEFAULT 200 NOT NULL,
    remote_ip character varying(64),
    summary text,
    response_meta jsonb DEFAULT '{}'::jsonb NOT NULL
);
-- reconcile coloane cts_api_log (drift; nullable, idempotent)
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS ts timestamp with time zone DEFAULT now();
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS action character varying(32);
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS email_ids jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS requested integer DEFAULT 0;
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS success integer DEFAULT 0;
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS total integer DEFAULT 0;
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS http_status integer DEFAULT 200;
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS remote_ip character varying(64);
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS summary text;
ALTER TABLE public.cts_api_log ADD COLUMN IF NOT EXISTS response_meta jsonb DEFAULT '{}'::jsonb;

CREATE SEQUENCE IF NOT EXISTS public.cts_api_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.cts_api_log_id_seq OWNED BY public.cts_api_log.id;

CREATE TABLE IF NOT EXISTS public.cts_ground_truth (
    id bigint NOT NULL,
    email_id bigint,
    message_id text,
    cts_category character varying(32),
    cts_department character varying(32),
    cts_reply_text text,
    cts_reply_at timestamp with time zone,
    cts_status character varying(32),
    source character varying(20) DEFAULT 'iris_sync'::character varying,
    raw jsonb,
    fetched_at timestamp with time zone DEFAULT now(),
    cts_category_prev character varying(32),
    cts_department_prev character varying(32),
    changed_at timestamp with time zone,
    last_synced_at timestamp with time zone,
    cts_direction character varying(12),
    cts_reply_html text,
    cts_attachments jsonb,
    cts_solved_at timestamp with time zone,
    cts_deleted_at timestamp with time zone,
    cts_thread_key text
);
-- reconcile coloane cts_ground_truth (drift; nullable, idempotent)
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS message_id text;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_category character varying(32);
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_department character varying(32);
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_reply_text text;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_reply_at timestamp with time zone;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_status character varying(32);
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS source character varying(20) DEFAULT 'iris_sync'::character varying;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS raw jsonb;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS fetched_at timestamp with time zone DEFAULT now();
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_category_prev character varying(32);
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_department_prev character varying(32);
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS changed_at timestamp with time zone;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS last_synced_at timestamp with time zone;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_direction character varying(12);
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_reply_html text;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_attachments jsonb;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_solved_at timestamp with time zone;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_deleted_at timestamp with time zone;
ALTER TABLE public.cts_ground_truth ADD COLUMN IF NOT EXISTS cts_thread_key text;

CREATE SEQUENCE IF NOT EXISTS public.cts_ground_truth_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.cts_ground_truth_id_seq OWNED BY public.cts_ground_truth.id;

CREATE TABLE IF NOT EXISTS public.delivery_queue (
    id bigint NOT NULL,
    email_id bigint NOT NULL,
    enqueued_at timestamp with time zone DEFAULT now(),
    delivered_at timestamp with time zone,
    delivered_to_admin boolean DEFAULT false,
    pull_attempts integer DEFAULT 0
);
-- reconcile coloane delivery_queue (drift; nullable, idempotent)
ALTER TABLE public.delivery_queue ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.delivery_queue ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.delivery_queue ADD COLUMN IF NOT EXISTS enqueued_at timestamp with time zone DEFAULT now();
ALTER TABLE public.delivery_queue ADD COLUMN IF NOT EXISTS delivered_at timestamp with time zone;
ALTER TABLE public.delivery_queue ADD COLUMN IF NOT EXISTS delivered_to_admin boolean DEFAULT false;
ALTER TABLE public.delivery_queue ADD COLUMN IF NOT EXISTS pull_attempts integer DEFAULT 0;

CREATE SEQUENCE IF NOT EXISTS public.delivery_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.delivery_queue_id_seq OWNED BY public.delivery_queue.id;

CREATE TABLE IF NOT EXISTS public.email_spam (
    email_id bigint NOT NULL,
    spam_score numeric(5,2) DEFAULT 0 NOT NULL,
    spam_reasons jsonb DEFAULT '[]'::jsonb NOT NULL,
    override boolean,
    reviewed_by character varying(100),
    reviewed_at timestamp with time zone,
    computed_at timestamp with time zone DEFAULT now() NOT NULL
);
-- reconcile coloane email_spam (drift; nullable, idempotent)
ALTER TABLE public.email_spam ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.email_spam ADD COLUMN IF NOT EXISTS spam_score numeric(5,2) DEFAULT 0;
ALTER TABLE public.email_spam ADD COLUMN IF NOT EXISTS spam_reasons jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.email_spam ADD COLUMN IF NOT EXISTS override boolean;
ALTER TABLE public.email_spam ADD COLUMN IF NOT EXISTS reviewed_by character varying(100);
ALTER TABLE public.email_spam ADD COLUMN IF NOT EXISTS reviewed_at timestamp with time zone;
ALTER TABLE public.email_spam ADD COLUMN IF NOT EXISTS computed_at timestamp with time zone DEFAULT now();

CREATE TABLE IF NOT EXISTS public.emails (
    id bigint NOT NULL,
    graph_message_id character varying(255) NOT NULL,
    conversation_id character varying(255),
    internet_message_id character varying(500),
    subject text,
    from_address character varying(320),
    from_name character varying(255),
    to_addresses jsonb,
    cc_addresses jsonb,
    bcc_addresses jsonb,
    reply_to jsonb,
    received_at timestamp with time zone NOT NULL,
    body_html text,
    body_text text,
    has_attachments boolean DEFAULT false,
    importance character varying(20),
    is_read boolean DEFAULT false,
    raw_graph_payload jsonb NOT NULL,
    fetched_at timestamp with time zone DEFAULT now(),
    processed_at timestamp with time zone,
    status character varying(30) DEFAULT 'pending'::character varying NOT NULL,
    client_id bigint,
    category character varying(30),
    phishing_score numeric(5,2),
    phishing_reasons jsonb,
    needs_human_review boolean DEFAULT false,
    reviewed_by character varying(100),
    reviewed_at timestamp with time zone,
    review_decision character varying(30),
    error_message text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    email_headers jsonb DEFAULT '{}'::jsonb NOT NULL,
    ai_category character varying(20),
    ai_result jsonb,
    ai_status character varying(12) DEFAULT 'pending'::character varying NOT NULL,
    ai_processed_at timestamp with time zone,
    ai_category_manual boolean DEFAULT false,
    queue_status character varying(24) DEFAULT 'queued_general'::character varying NOT NULL,
    manual_clean boolean DEFAULT false NOT NULL,
    sent_to_cts_at timestamp with time zone,
    cts_send_error text,
    cts_send_attempts integer DEFAULT 0 NOT NULL,
    manual_review_state character varying(20),
    manual_review_reason character varying(20),
    manual_review_batch date,
    manual_review_picked_at timestamp with time zone,
    manual_review_result character varying(20),
    manual_review_done_at timestamp with time zone,
    manual_review_by character varying(100),
    translation_status character varying(20),
    source_lang character varying(16),
    translated_subject text,
    translated_text text,
    translated_at timestamp with time zone,
    translation_model character varying(80),
    translation_error text,
    ai_department text,
    ai_department_result jsonb,
    ai_department_manual boolean DEFAULT false,
    ai_department_at timestamp with time zone,
    auth_verdict text,
    auth_result jsonb,
    ai_priority character varying(8),
    ai_priority_result jsonb,
    ai_priority_at timestamp with time zone,
    ai_priority_manual boolean DEFAULT false,
    ai_autoreply text,
    ai_autoreply_result jsonb,
    ai_autoreply_at timestamp with time zone,
    ai_autoreply_status character varying(12),
    ai_autoreply_confidence real,
    ai_intent jsonb,
    ai_intent_at timestamp with time zone,
    dedup_of bigint
);
-- reconcile coloane emails (drift; nullable, idempotent)
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS graph_message_id character varying(255);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS conversation_id character varying(255);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS internet_message_id character varying(500);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS subject text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS from_address character varying(320);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS from_name character varying(255);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS to_addresses jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS cc_addresses jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS bcc_addresses jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS reply_to jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS received_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS body_html text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS body_text text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS has_attachments boolean DEFAULT false;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS importance character varying(20);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS is_read boolean DEFAULT false;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS raw_graph_payload jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS fetched_at timestamp with time zone DEFAULT now();
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS processed_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS status character varying(30) DEFAULT 'pending'::character varying;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS client_id bigint;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS category character varying(30);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS phishing_score numeric(5,2);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS phishing_reasons jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS needs_human_review boolean DEFAULT false;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS reviewed_by character varying(100);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS reviewed_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS review_decision character varying(30);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS error_message text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS updated_at timestamp with time zone DEFAULT now();
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS email_headers jsonb DEFAULT '{}'::jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_category character varying(20);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_result jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_status character varying(12) DEFAULT 'pending'::character varying;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_processed_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_category_manual boolean DEFAULT false;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS queue_status character varying(24) DEFAULT 'queued_general'::character varying;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS manual_clean boolean DEFAULT false;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS sent_to_cts_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS cts_send_error text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS cts_send_attempts integer DEFAULT 0;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS manual_review_state character varying(20);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS manual_review_reason character varying(20);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS manual_review_batch date;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS manual_review_picked_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS manual_review_result character varying(20);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS manual_review_done_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS manual_review_by character varying(100);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS translation_status character varying(20);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS source_lang character varying(16);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS translated_subject text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS translated_text text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS translated_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS translation_model character varying(80);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS translation_error text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_department text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_department_result jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_department_manual boolean DEFAULT false;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_department_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS auth_verdict text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS auth_result jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_priority character varying(8);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_priority_result jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_priority_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_priority_manual boolean DEFAULT false;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_autoreply text;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_autoreply_result jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_autoreply_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_autoreply_status character varying(12);
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_autoreply_confidence real;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_intent jsonb;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS ai_intent_at timestamp with time zone;
ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS dedup_of bigint;

CREATE SEQUENCE IF NOT EXISTS public.emails_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.emails_id_seq OWNED BY public.emails.id;

CREATE SEQUENCE IF NOT EXISTS public.employee_department_mapping_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.employee_department_mapping_id_seq OWNED BY public.employee_department_mapping.id;

CREATE TABLE IF NOT EXISTS public.extracted_records (
    id bigint NOT NULL,
    pattern_id bigint NOT NULL,
    email_id bigint NOT NULL,
    data jsonb DEFAULT '{}'::jsonb NOT NULL,
    model character varying(80),
    extracted_at timestamp with time zone DEFAULT now() NOT NULL
);
-- reconcile coloane extracted_records (drift; nullable, idempotent)
ALTER TABLE public.extracted_records ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.extracted_records ADD COLUMN IF NOT EXISTS pattern_id bigint;
ALTER TABLE public.extracted_records ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.extracted_records ADD COLUMN IF NOT EXISTS data jsonb DEFAULT '{}'::jsonb;
ALTER TABLE public.extracted_records ADD COLUMN IF NOT EXISTS model character varying(80);
ALTER TABLE public.extracted_records ADD COLUMN IF NOT EXISTS extracted_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.extracted_records_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.extracted_records_id_seq OWNED BY public.extracted_records.id;

CREATE TABLE IF NOT EXISTS public.extraction_queue (
    id bigint NOT NULL,
    pattern_id bigint NOT NULL,
    email_id bigint NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    processed_at timestamp with time zone
);
-- reconcile coloane extraction_queue (drift; nullable, idempotent)
ALTER TABLE public.extraction_queue ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.extraction_queue ADD COLUMN IF NOT EXISTS pattern_id bigint;
ALTER TABLE public.extraction_queue ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.extraction_queue ADD COLUMN IF NOT EXISTS status character varying(16) DEFAULT 'pending'::character varying;
ALTER TABLE public.extraction_queue ADD COLUMN IF NOT EXISTS attempts integer DEFAULT 0;
ALTER TABLE public.extraction_queue ADD COLUMN IF NOT EXISTS error text;
ALTER TABLE public.extraction_queue ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();
ALTER TABLE public.extraction_queue ADD COLUMN IF NOT EXISTS processed_at timestamp with time zone;

CREATE SEQUENCE IF NOT EXISTS public.extraction_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.extraction_queue_id_seq OWNED BY public.extraction_queue.id;

CREATE SEQUENCE IF NOT EXISTS public.golden_bad_templates_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.golden_bad_templates_id_seq OWNED BY public.golden_bad_templates.id;

CREATE TABLE IF NOT EXISTS public.ndr_log (
    id bigint NOT NULL,
    email_id bigint,
    failed_address character varying(320) NOT NULL,
    error_code character varying(50),
    error_message text,
    original_subject text,
    detected_at timestamp with time zone DEFAULT now(),
    included_in_report date
);
-- reconcile coloane ndr_log (drift; nullable, idempotent)
ALTER TABLE public.ndr_log ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.ndr_log ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.ndr_log ADD COLUMN IF NOT EXISTS failed_address character varying(320);
ALTER TABLE public.ndr_log ADD COLUMN IF NOT EXISTS error_code character varying(50);
ALTER TABLE public.ndr_log ADD COLUMN IF NOT EXISTS error_message text;
ALTER TABLE public.ndr_log ADD COLUMN IF NOT EXISTS original_subject text;
ALTER TABLE public.ndr_log ADD COLUMN IF NOT EXISTS detected_at timestamp with time zone DEFAULT now();
ALTER TABLE public.ndr_log ADD COLUMN IF NOT EXISTS included_in_report date;

CREATE SEQUENCE IF NOT EXISTS public.ndr_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ndr_log_id_seq OWNED BY public.ndr_log.id;

CREATE TABLE IF NOT EXISTS public.prompt_history (
    id bigint NOT NULL,
    prompt_id bigint NOT NULL,
    version integer NOT NULL,
    system_prompt text NOT NULL,
    user_prompt_template text NOT NULL,
    model character varying(100),
    changed_by character varying(100),
    changed_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane prompt_history (drift; nullable, idempotent)
ALTER TABLE public.prompt_history ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.prompt_history ADD COLUMN IF NOT EXISTS prompt_id bigint;
ALTER TABLE public.prompt_history ADD COLUMN IF NOT EXISTS version integer;
ALTER TABLE public.prompt_history ADD COLUMN IF NOT EXISTS system_prompt text;
ALTER TABLE public.prompt_history ADD COLUMN IF NOT EXISTS user_prompt_template text;
ALTER TABLE public.prompt_history ADD COLUMN IF NOT EXISTS model character varying(100);
ALTER TABLE public.prompt_history ADD COLUMN IF NOT EXISTS changed_by character varying(100);
ALTER TABLE public.prompt_history ADD COLUMN IF NOT EXISTS changed_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.prompt_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.prompt_history_id_seq OWNED BY public.prompt_history.id;

CREATE TABLE IF NOT EXISTS public.prompts (
    id bigint NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    system_prompt text NOT NULL,
    user_prompt_template text NOT NULL,
    model character varying(100) NOT NULL,
    temperature numeric(3,2) DEFAULT 0.0,
    max_tokens integer DEFAULT 500,
    version integer DEFAULT 1,
    is_active boolean DEFAULT true,
    created_by character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane prompts (drift; nullable, idempotent)
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS code character varying(50);
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS name character varying(200);
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS description text;
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS system_prompt text;
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS user_prompt_template text;
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS model character varying(100);
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS temperature numeric(3,2) DEFAULT 0.0;
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS max_tokens integer DEFAULT 500;
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS version integer DEFAULT 1;
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true;
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS created_by character varying(100);
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();
ALTER TABLE public.prompts ADD COLUMN IF NOT EXISTS updated_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.prompts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.prompts_id_seq OWNED BY public.prompts.id;

CREATE TABLE IF NOT EXISTS public.quarantine_feedback (
    id bigint NOT NULL,
    email_id bigint NOT NULL,
    decision character varying(20) DEFAULT 'not_phishing'::character varying NOT NULL,
    scope_type character varying(20) NOT NULL,
    scope_value character varying(320) NOT NULL,
    suppressed_codes jsonb DEFAULT '[]'::jsonb NOT NULL,
    reasons_snapshot jsonb,
    score_at_feedback numeric(5,2),
    created_by character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
-- reconcile coloane quarantine_feedback (drift; nullable, idempotent)
ALTER TABLE public.quarantine_feedback ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.quarantine_feedback ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.quarantine_feedback ADD COLUMN IF NOT EXISTS decision character varying(20) DEFAULT 'not_phishing'::character varying;
ALTER TABLE public.quarantine_feedback ADD COLUMN IF NOT EXISTS scope_type character varying(20);
ALTER TABLE public.quarantine_feedback ADD COLUMN IF NOT EXISTS scope_value character varying(320);
ALTER TABLE public.quarantine_feedback ADD COLUMN IF NOT EXISTS suppressed_codes jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.quarantine_feedback ADD COLUMN IF NOT EXISTS reasons_snapshot jsonb;
ALTER TABLE public.quarantine_feedback ADD COLUMN IF NOT EXISTS score_at_feedback numeric(5,2);
ALTER TABLE public.quarantine_feedback ADD COLUMN IF NOT EXISTS created_by character varying(100);
ALTER TABLE public.quarantine_feedback ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.quarantine_feedback_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.quarantine_feedback_id_seq OWNED BY public.quarantine_feedback.id;

CREATE TABLE IF NOT EXISTS public.quarantine_strict (
    id bigint NOT NULL,
    email_id bigint NOT NULL,
    reason character varying(100) NOT NULL,
    detected_indicators jsonb,
    review_status character varying(30) DEFAULT 'pending'::character varying,
    reviewed_by character varying(100),
    reviewed_at timestamp with time zone,
    decision character varying(30),
    created_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane quarantine_strict (drift; nullable, idempotent)
ALTER TABLE public.quarantine_strict ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.quarantine_strict ADD COLUMN IF NOT EXISTS email_id bigint;
ALTER TABLE public.quarantine_strict ADD COLUMN IF NOT EXISTS reason character varying(100);
ALTER TABLE public.quarantine_strict ADD COLUMN IF NOT EXISTS detected_indicators jsonb;
ALTER TABLE public.quarantine_strict ADD COLUMN IF NOT EXISTS review_status character varying(30) DEFAULT 'pending'::character varying;
ALTER TABLE public.quarantine_strict ADD COLUMN IF NOT EXISTS reviewed_by character varying(100);
ALTER TABLE public.quarantine_strict ADD COLUMN IF NOT EXISTS reviewed_at timestamp with time zone;
ALTER TABLE public.quarantine_strict ADD COLUMN IF NOT EXISTS decision character varying(30);
ALTER TABLE public.quarantine_strict ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.quarantine_strict_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.quarantine_strict_id_seq OWNED BY public.quarantine_strict.id;

CREATE TABLE IF NOT EXISTS public.report_patterns (
    id bigint NOT NULL,
    group_label character varying(220),
    system_name character varying(220),
    from_addresses jsonb DEFAULT '[]'::jsonb NOT NULL,
    fingerprints jsonb DEFAULT '[]'::jsonb NOT NULL,
    sample_subject text,
    topic text,
    suggested_action text,
    action character varying(64) DEFAULT 'daily_digest'::character varying NOT NULL,
    frequency character varying(32),
    email_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    email_count integer DEFAULT 0 NOT NULL,
    total_matched integer DEFAULT 0 NOT NULL,
    status character varying(24) DEFAULT 'active'::character varying NOT NULL,
    created_by character varying(160),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone,
    extract_fields jsonb DEFAULT '[]'::jsonb NOT NULL,
    extract_prompt text,
    extract_enabled boolean DEFAULT false NOT NULL
);
-- reconcile coloane report_patterns (drift; nullable, idempotent)
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS group_label character varying(220);
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS system_name character varying(220);
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS from_addresses jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS fingerprints jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS sample_subject text;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS topic text;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS suggested_action text;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS action character varying(64) DEFAULT 'daily_digest'::character varying;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS frequency character varying(32);
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS email_ids jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS email_count integer DEFAULT 0;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS total_matched integer DEFAULT 0;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS status character varying(24) DEFAULT 'active'::character varying;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS created_by character varying(160);
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS last_seen_at timestamp with time zone;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS extract_fields jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS extract_prompt text;
ALTER TABLE public.report_patterns ADD COLUMN IF NOT EXISTS extract_enabled boolean DEFAULT false;

CREATE SEQUENCE IF NOT EXISTS public.report_patterns_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.report_patterns_id_seq OWNED BY public.report_patterns.id;

CREATE TABLE IF NOT EXISTS public.settings (
    key character varying(100) NOT NULL,
    value jsonb NOT NULL,
    description text,
    updated_by character varying(100),
    updated_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane settings (drift; nullable, idempotent)
ALTER TABLE public.settings ADD COLUMN IF NOT EXISTS key character varying(100);
ALTER TABLE public.settings ADD COLUMN IF NOT EXISTS value jsonb;
ALTER TABLE public.settings ADD COLUMN IF NOT EXISTS description text;
ALTER TABLE public.settings ADD COLUMN IF NOT EXISTS updated_by character varying(100);
ALTER TABLE public.settings ADD COLUMN IF NOT EXISTS updated_at timestamp with time zone DEFAULT now();

CREATE SEQUENCE IF NOT EXISTS public.spam_sender_reputation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.spam_sender_reputation_id_seq OWNED BY public.spam_sender_reputation.id;

CREATE SEQUENCE IF NOT EXISTS public.spam_unsubscribe_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.spam_unsubscribe_log_id_seq OWNED BY public.spam_unsubscribe_log.id;

CREATE TABLE IF NOT EXISTS public.sso_nonces (
    nonce text NOT NULL,
    used_at timestamp with time zone DEFAULT now()
);
-- reconcile coloane sso_nonces (drift; nullable, idempotent)
ALTER TABLE public.sso_nonces ADD COLUMN IF NOT EXISTS nonce text;
ALTER TABLE public.sso_nonces ADD COLUMN IF NOT EXISTS used_at timestamp with time zone DEFAULT now();

CREATE TABLE IF NOT EXISTS public.suppression_rules (
    id bigint NOT NULL,
    scope_type character varying(20) NOT NULL,
    scope_value character varying(320) NOT NULL,
    suppressed_codes jsonb DEFAULT '[]'::jsonb NOT NULL,
    active boolean DEFAULT true NOT NULL,
    from_feedback_id bigint,
    created_by character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone,
    template_fingerprint text,
    fingerprint_k smallint DEFAULT 3
);
-- reconcile coloane suppression_rules (drift; nullable, idempotent)
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS id bigint;
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS scope_type character varying(20);
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS scope_value character varying(320);
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS suppressed_codes jsonb DEFAULT '[]'::jsonb;
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS active boolean DEFAULT true;
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS from_feedback_id bigint;
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS created_by character varying(100);
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now();
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS updated_at timestamp with time zone DEFAULT now();
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS expires_at timestamp with time zone;
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS template_fingerprint text;
ALTER TABLE public.suppression_rules ADD COLUMN IF NOT EXISTS fingerprint_k smallint DEFAULT 3;

CREATE SEQUENCE IF NOT EXISTS public.suppression_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.suppression_rules_id_seq OWNED BY public.suppression_rules.id;

ALTER TABLE ONLY public.admin_users ALTER COLUMN id SET DEFAULT nextval('public.admin_users_id_seq'::regclass);

ALTER TABLE ONLY public.ai_autoreply_feedback ALTER COLUMN id SET DEFAULT nextval('public.ai_autoreply_feedback_id_seq'::regclass);

ALTER TABLE ONLY public.ai_autoreply_prompt_versions ALTER COLUMN id SET DEFAULT nextval('public.ai_autoreply_prompt_versions_id_seq'::regclass);

ALTER TABLE ONLY public.ai_call_log ALTER COLUMN id SET DEFAULT nextval('public.ai_call_log_id_seq'::regclass);

ALTER TABLE ONLY public.ai_category_corrections ALTER COLUMN id SET DEFAULT nextval('public.ai_category_corrections_id_seq'::regclass);

ALTER TABLE ONLY public.ai_category_prompt_versions ALTER COLUMN id SET DEFAULT nextval('public.ai_category_prompt_versions_id_seq'::regclass);

ALTER TABLE ONLY public.ai_department_corrections ALTER COLUMN id SET DEFAULT nextval('public.ai_department_corrections_id_seq'::regclass);

ALTER TABLE ONLY public.ai_department_prompt_versions ALTER COLUMN id SET DEFAULT nextval('public.ai_department_prompt_versions_id_seq'::regclass);

ALTER TABLE ONLY public.ai_priority_corrections ALTER COLUMN id SET DEFAULT nextval('public.ai_priority_corrections_id_seq'::regclass);

ALTER TABLE ONLY public.ai_priority_prompt_versions ALTER COLUMN id SET DEFAULT nextval('public.ai_priority_prompt_versions_id_seq'::regclass);

ALTER TABLE ONLY public.ai_reports ALTER COLUMN id SET DEFAULT nextval('public.ai_reports_id_seq'::regclass);

ALTER TABLE ONLY public.api_keys ALTER COLUMN id SET DEFAULT nextval('public.api_keys_id_seq'::regclass);

ALTER TABLE ONLY public.attachments ALTER COLUMN id SET DEFAULT nextval('public.attachments_id_seq'::regclass);

ALTER TABLE ONLY public.audit_log ALTER COLUMN id SET DEFAULT nextval('public.audit_log_id_seq'::regclass);

ALTER TABLE ONLY public.clients ALTER COLUMN id SET DEFAULT nextval('public.clients_id_seq'::regclass);

ALTER TABLE ONLY public.cts_api_log ALTER COLUMN id SET DEFAULT nextval('public.cts_api_log_id_seq'::regclass);

ALTER TABLE ONLY public.cts_ground_truth ALTER COLUMN id SET DEFAULT nextval('public.cts_ground_truth_id_seq'::regclass);

ALTER TABLE ONLY public.delivery_queue ALTER COLUMN id SET DEFAULT nextval('public.delivery_queue_id_seq'::regclass);

ALTER TABLE ONLY public.emails ALTER COLUMN id SET DEFAULT nextval('public.emails_id_seq'::regclass);

ALTER TABLE ONLY public.extracted_records ALTER COLUMN id SET DEFAULT nextval('public.extracted_records_id_seq'::regclass);

ALTER TABLE ONLY public.extraction_queue ALTER COLUMN id SET DEFAULT nextval('public.extraction_queue_id_seq'::regclass);

ALTER TABLE ONLY public.ndr_log ALTER COLUMN id SET DEFAULT nextval('public.ndr_log_id_seq'::regclass);

ALTER TABLE ONLY public.prompt_history ALTER COLUMN id SET DEFAULT nextval('public.prompt_history_id_seq'::regclass);

ALTER TABLE ONLY public.prompts ALTER COLUMN id SET DEFAULT nextval('public.prompts_id_seq'::regclass);

ALTER TABLE ONLY public.quarantine_feedback ALTER COLUMN id SET DEFAULT nextval('public.quarantine_feedback_id_seq'::regclass);

ALTER TABLE ONLY public.quarantine_strict ALTER COLUMN id SET DEFAULT nextval('public.quarantine_strict_id_seq'::regclass);

ALTER TABLE ONLY public.report_patterns ALTER COLUMN id SET DEFAULT nextval('public.report_patterns_id_seq'::regclass);

ALTER TABLE ONLY public.suppression_rules ALTER COLUMN id SET DEFAULT nextval('public.suppression_rules_id_seq'::regclass);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'admin_users_pkey') THEN
    ALTER TABLE ONLY public.admin_users
    ADD CONSTRAINT admin_users_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'admin_users_username_key') THEN
    ALTER TABLE ONLY public.admin_users
    ADD CONSTRAINT admin_users_username_key UNIQUE (username);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_autoreply_feedback_pkey') THEN
    ALTER TABLE ONLY public.ai_autoreply_feedback
    ADD CONSTRAINT ai_autoreply_feedback_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_autoreply_prompt_versions_pkey') THEN
    ALTER TABLE ONLY public.ai_autoreply_prompt_versions
    ADD CONSTRAINT ai_autoreply_prompt_versions_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_call_log_pkey') THEN
    ALTER TABLE ONLY public.ai_call_log
    ADD CONSTRAINT ai_call_log_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_category_corrections_pkey') THEN
    ALTER TABLE ONLY public.ai_category_corrections
    ADD CONSTRAINT ai_category_corrections_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_category_prompt_versions_pkey') THEN
    ALTER TABLE ONLY public.ai_category_prompt_versions
    ADD CONSTRAINT ai_category_prompt_versions_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_category_prompts_pkey') THEN
    ALTER TABLE ONLY public.ai_category_prompts
    ADD CONSTRAINT ai_category_prompts_pkey PRIMARY KEY (category);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_department_corrections_pkey') THEN
    ALTER TABLE ONLY public.ai_department_corrections
    ADD CONSTRAINT ai_department_corrections_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_department_prompt_versions_pkey') THEN
    ALTER TABLE ONLY public.ai_department_prompt_versions
    ADD CONSTRAINT ai_department_prompt_versions_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_department_prompts_pkey') THEN
    ALTER TABLE ONLY public.ai_department_prompts
    ADD CONSTRAINT ai_department_prompts_pkey PRIMARY KEY (department);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_priority_corrections_pkey') THEN
    ALTER TABLE ONLY public.ai_priority_corrections
    ADD CONSTRAINT ai_priority_corrections_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_priority_prompt_versions_pkey') THEN
    ALTER TABLE ONLY public.ai_priority_prompt_versions
    ADD CONSTRAINT ai_priority_prompt_versions_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_reports_pkey') THEN
    ALTER TABLE ONLY public.ai_reports
    ADD CONSTRAINT ai_reports_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'api_keys_label_key') THEN
    ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_label_key UNIQUE (label);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'api_keys_pkey') THEN
    ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'attachments_pkey') THEN
    ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'audit_log_pkey') THEN
    ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'clients_iris_client_id_key') THEN
    ALTER TABLE ONLY public.clients
    ADD CONSTRAINT clients_iris_client_id_key UNIQUE (iris_client_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'clients_pkey') THEN
    ALTER TABLE ONLY public.clients
    ADD CONSTRAINT clients_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cts_api_log_pkey') THEN
    ALTER TABLE ONLY public.cts_api_log
    ADD CONSTRAINT cts_api_log_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cts_ground_truth_pkey') THEN
    ALTER TABLE ONLY public.cts_ground_truth
    ADD CONSTRAINT cts_ground_truth_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cts_ground_truth_source_message_id_key') THEN
    ALTER TABLE ONLY public.cts_ground_truth
    ADD CONSTRAINT cts_ground_truth_source_message_id_key UNIQUE (source, message_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'delivery_queue_email_id_key') THEN
    ALTER TABLE ONLY public.delivery_queue
    ADD CONSTRAINT delivery_queue_email_id_key UNIQUE (email_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'delivery_queue_pkey') THEN
    ALTER TABLE ONLY public.delivery_queue
    ADD CONSTRAINT delivery_queue_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'email_spam_pkey') THEN
    ALTER TABLE ONLY public.email_spam
    ADD CONSTRAINT email_spam_pkey PRIMARY KEY (email_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'emails_graph_message_id_key') THEN
    ALTER TABLE ONLY public.emails
    ADD CONSTRAINT emails_graph_message_id_key UNIQUE (graph_message_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'emails_pkey') THEN
    ALTER TABLE ONLY public.emails
    ADD CONSTRAINT emails_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'extracted_records_pattern_id_email_id_key') THEN
    ALTER TABLE ONLY public.extracted_records
    ADD CONSTRAINT extracted_records_pattern_id_email_id_key UNIQUE (pattern_id, email_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'extracted_records_pkey') THEN
    ALTER TABLE ONLY public.extracted_records
    ADD CONSTRAINT extracted_records_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'extraction_queue_pattern_id_email_id_key') THEN
    ALTER TABLE ONLY public.extraction_queue
    ADD CONSTRAINT extraction_queue_pattern_id_email_id_key UNIQUE (pattern_id, email_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'extraction_queue_pkey') THEN
    ALTER TABLE ONLY public.extraction_queue
    ADD CONSTRAINT extraction_queue_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ndr_log_pkey') THEN
    ALTER TABLE ONLY public.ndr_log
    ADD CONSTRAINT ndr_log_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'prompt_history_pkey') THEN
    ALTER TABLE ONLY public.prompt_history
    ADD CONSTRAINT prompt_history_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'prompts_code_key') THEN
    ALTER TABLE ONLY public.prompts
    ADD CONSTRAINT prompts_code_key UNIQUE (code);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'prompts_pkey') THEN
    ALTER TABLE ONLY public.prompts
    ADD CONSTRAINT prompts_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'quarantine_feedback_pkey') THEN
    ALTER TABLE ONLY public.quarantine_feedback
    ADD CONSTRAINT quarantine_feedback_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'quarantine_strict_pkey') THEN
    ALTER TABLE ONLY public.quarantine_strict
    ADD CONSTRAINT quarantine_strict_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'report_patterns_pkey') THEN
    ALTER TABLE ONLY public.report_patterns
    ADD CONSTRAINT report_patterns_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'settings_pkey') THEN
    ALTER TABLE ONLY public.settings
    ADD CONSTRAINT settings_pkey PRIMARY KEY (key);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sso_nonces_pkey') THEN
    ALTER TABLE ONLY public.sso_nonces
    ADD CONSTRAINT sso_nonces_pkey PRIMARY KEY (nonce);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'suppression_rules_pkey') THEN
    ALTER TABLE ONLY public.suppression_rules
    ADD CONSTRAINT suppression_rules_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_suppression_scope') THEN
    ALTER TABLE ONLY public.suppression_rules
    ADD CONSTRAINT uq_suppression_scope UNIQUE (scope_type, scope_value);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ai_call_log_created ON public.ai_call_log USING btree (created_at);

CREATE INDEX IF NOT EXISTS idx_ai_call_log_email ON public.ai_call_log USING btree (email_id);

CREATE INDEX IF NOT EXISTS idx_ai_call_log_task ON public.ai_call_log USING btree (task);

CREATE INDEX IF NOT EXISTS idx_ai_corr_email ON public.ai_category_corrections USING btree (email_id);

CREATE INDEX IF NOT EXISTS idx_ai_reports_type_time ON public.ai_reports USING btree (report_type, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_attachments_email ON public.attachments USING btree (email_id);

CREATE INDEX IF NOT EXISTS idx_attachments_scan_verdict ON public.attachments USING btree (scan_verdict) WHERE ((scan_verdict IS NOT NULL) AND (scan_verdict <> 'clean'::text));

CREATE INDEX IF NOT EXISTS idx_attachments_sha ON public.attachments USING btree (sha256);

CREATE INDEX IF NOT EXISTS idx_audit_actor ON public.audit_log USING btree (actor);

CREATE INDEX IF NOT EXISTS idx_audit_created ON public.audit_log USING btree (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_clients_active ON public.clients USING btree (is_active);

CREATE INDEX IF NOT EXISTS idx_clients_emails ON public.clients USING gin (emails);

CREATE INDEX IF NOT EXISTS idx_clients_iris ON public.clients USING btree (iris_client_id);

CREATE INDEX IF NOT EXISTS idx_cts_api_log_ts ON public.cts_api_log USING btree (ts DESC);

CREATE INDEX IF NOT EXISTS idx_cts_gt_changed ON public.cts_ground_truth USING btree (changed_at);

CREATE INDEX IF NOT EXISTS idx_cts_gt_dept ON public.cts_ground_truth USING btree (cts_department);

CREATE INDEX IF NOT EXISTS idx_cts_gt_direction ON public.cts_ground_truth USING btree (cts_direction);

CREATE INDEX IF NOT EXISTS idx_cts_gt_email ON public.cts_ground_truth USING btree (email_id);

CREATE INDEX IF NOT EXISTS idx_cts_gt_msgid ON public.cts_ground_truth USING btree (message_id);

CREATE INDEX IF NOT EXISTS idx_cts_gt_thread ON public.cts_ground_truth USING btree (cts_thread_key) WHERE (cts_thread_key IS NOT NULL);

CREATE INDEX IF NOT EXISTS idx_dqueue_pending ON public.delivery_queue USING btree (delivered_to_admin) WHERE (delivered_to_admin = false);

CREATE INDEX IF NOT EXISTS idx_email_spam_score ON public.email_spam USING btree (spam_score);

CREATE INDEX IF NOT EXISTS idx_emails_ai_autoreply_status ON public.emails USING btree (ai_autoreply_status);

CREATE INDEX IF NOT EXISTS idx_emails_ai_category ON public.emails USING btree (ai_category);

CREATE INDEX IF NOT EXISTS idx_emails_ai_intent ON public.emails USING gin (ai_intent);

CREATE INDEX IF NOT EXISTS idx_emails_ai_priority ON public.emails USING btree (ai_priority);

CREATE INDEX IF NOT EXISTS idx_emails_ai_status ON public.emails USING btree (ai_status);

CREATE INDEX IF NOT EXISTS idx_emails_auth_verdict ON public.emails USING btree (auth_verdict) WHERE (auth_verdict IS NOT NULL);

CREATE INDEX IF NOT EXISTS idx_emails_category ON public.emails USING btree (category);

CREATE INDEX IF NOT EXISTS idx_emails_client ON public.emails USING btree (client_id);

CREATE INDEX IF NOT EXISTS idx_emails_dedup_lookup ON public.emails USING btree (from_address, subject, received_at DESC) WHERE ((status)::text <> 'duplicate'::text);

CREATE INDEX IF NOT EXISTS idx_emails_dedup_of ON public.emails USING btree (dedup_of) WHERE (dedup_of IS NOT NULL);

CREATE INDEX IF NOT EXISTS idx_emails_from ON public.emails USING btree (from_address);

CREATE INDEX IF NOT EXISTS idx_emails_hdr_msgid ON public.emails USING btree (((email_headers ->> 'message_id'::text)));

CREATE INDEX IF NOT EXISTS idx_emails_headers ON public.emails USING gin (email_headers);

CREATE INDEX IF NOT EXISTS idx_emails_mr_batch ON public.emails USING btree (manual_review_batch);

CREATE INDEX IF NOT EXISTS idx_emails_mr_pending ON public.emails USING btree (manual_review_state) WHERE ((manual_review_state)::text = 'pending'::text);

CREATE INDEX IF NOT EXISTS idx_emails_queue_status ON public.emails USING btree (queue_status);

CREATE INDEX IF NOT EXISTS idx_emails_received ON public.emails USING btree (received_at DESC);

CREATE INDEX IF NOT EXISTS idx_emails_review ON public.emails USING btree (needs_human_review) WHERE (needs_human_review = true);

CREATE INDEX IF NOT EXISTS idx_emails_status ON public.emails USING btree (status);

CREATE INDEX IF NOT EXISTS idx_extq_pat_status ON public.extraction_queue USING btree (pattern_id, status);

CREATE INDEX IF NOT EXISTS idx_extrec_pat ON public.extracted_records USING btree (pattern_id, extracted_at DESC);

CREATE INDEX IF NOT EXISTS idx_ndr_address ON public.ndr_log USING btree (failed_address);

CREATE INDEX IF NOT EXISTS idx_ndr_report ON public.ndr_log USING btree (included_in_report);

CREATE INDEX IF NOT EXISTS idx_qstrict_status ON public.quarantine_strict USING btree (review_status);

CREATE INDEX IF NOT EXISTS idx_sso_nonces_used ON public.sso_nonces USING btree (used_at);

CREATE INDEX IF NOT EXISTS idx_suppression_lookup ON public.suppression_rules USING btree (scope_type, scope_value) WHERE active;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_call_log_email_id_fkey') THEN
    ALTER TABLE ONLY public.ai_call_log
    ADD CONSTRAINT ai_call_log_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.emails(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'attachments_email_id_fkey') THEN
    ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT attachments_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.emails(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'delivery_queue_email_id_fkey') THEN
    ALTER TABLE ONLY public.delivery_queue
    ADD CONSTRAINT delivery_queue_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.emails(id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'email_spam_email_id_fkey') THEN
    ALTER TABLE ONLY public.email_spam
    ADD CONSTRAINT email_spam_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.emails(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'emails_client_id_fkey') THEN
    ALTER TABLE ONLY public.emails
    ADD CONSTRAINT emails_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.clients(id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'emails_dedup_of_fkey') THEN
    ALTER TABLE ONLY public.emails
    ADD CONSTRAINT emails_dedup_of_fkey FOREIGN KEY (dedup_of) REFERENCES public.emails(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'extracted_records_pattern_id_fkey') THEN
    ALTER TABLE ONLY public.extracted_records
    ADD CONSTRAINT extracted_records_pattern_id_fkey FOREIGN KEY (pattern_id) REFERENCES public.report_patterns(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'extraction_queue_pattern_id_fkey') THEN
    ALTER TABLE ONLY public.extraction_queue
    ADD CONSTRAINT extraction_queue_pattern_id_fkey FOREIGN KEY (pattern_id) REFERENCES public.report_patterns(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ndr_log_email_id_fkey') THEN
    ALTER TABLE ONLY public.ndr_log
    ADD CONSTRAINT ndr_log_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.emails(id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'prompt_history_prompt_id_fkey') THEN
    ALTER TABLE ONLY public.prompt_history
    ADD CONSTRAINT prompt_history_prompt_id_fkey FOREIGN KEY (prompt_id) REFERENCES public.prompts(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'quarantine_feedback_email_id_fkey') THEN
    ALTER TABLE ONLY public.quarantine_feedback
    ADD CONSTRAINT quarantine_feedback_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.emails(id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'quarantine_strict_email_id_fkey') THEN
    ALTER TABLE ONLY public.quarantine_strict
    ADD CONSTRAINT quarantine_strict_email_id_fkey FOREIGN KEY (email_id) REFERENCES public.emails(id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'suppression_rules_from_feedback_id_fkey') THEN
    ALTER TABLE ONLY public.suppression_rules
    ADD CONSTRAINT suppression_rules_from_feedback_id_fkey FOREIGN KEY (from_feedback_id) REFERENCES public.quarantine_feedback(id);
  END IF;
END $$;

