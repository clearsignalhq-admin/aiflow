from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    # Supabase (server-side only — never expose to frontend)
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # Request body size limit in bytes (413 above this)
    max_request_bytes: int = 1_000_000

    # Request time budget. API Gateway HTTP APIs cut a request at 30 s, so every guard must be shorter,
    # otherwise the client sees a generic 503 while the Lambda keeps running (and spending LLM money).
    request_budget_seconds: float = 28.0       # total for one request
    simulation_timeout_seconds: float = 25.0   # simulate / resume
    llm_timeout_seconds: float = 25.0          # generate / chat
    min_llm_evaluation_seconds: float = 3.0    # below this, skip the LLM evaluation and use the mock one
    persist_reserve_seconds: float = 2.0       # kept free for saving the run

    # Test suites
    demo_max_cases_per_suite: int = 10
    approved_max_cases_per_suite: int = 50
    max_suites_per_user: int = 20
    max_suite_runs_per_suite: int = 20     # newest runs kept per suite
    suite_job_stale_minutes: int = 15      # a running job older than this is marked failed

    # Persisted simulation runs
    max_runs_per_user: int = 50
    run_retention_days: int = 30      # 0 = keep until pushed out by max_runs_per_user
    max_run_bytes: int = 500_000

    # Demo usage limits
    demo_max_executions_per_day: int = 10
    demo_max_llm_requests_per_day: int = 20

    # Approved user limits (0 = unlimited)
    approved_max_executions_per_day: int = 0
    approved_max_llm_requests_per_day: int = 0

    # Cloudflare Turnstile (leave empty to skip verification in dev)
    turnstile_secret_key: str = ""

    # Bootstrap: auto-promote this email to approved admin on startup
    admin_email: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
