"""Private model runs: no hosted tracing, stored Responses, or automatic retries."""
def private_run_config():
    from agents import RunConfig, ModelSettings
    from agents.models.openai_provider import OpenAIProvider
    from openai import AsyncOpenAI

    return RunConfig(
        tracing_disabled=True,
        model_settings=ModelSettings(store=False),
        model_provider=OpenAIProvider(openai_client=AsyncOpenAI(max_retries=0)),
    )
