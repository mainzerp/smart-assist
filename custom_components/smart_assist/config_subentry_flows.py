"""Subentry flow handlers for Smart Assist config flow."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .config_validators import (
    fetch_groq_models,
    fetch_model_providers,
    fetch_ollama_models,
    fetch_openrouter_models,
    validate_direct_alarm_timeout,
    validate_script_entity_id,
    validate_service_string,
    validate_groq_api_key,
)
from .const import (
    CONF_API_KEY,
    CONF_ASK_FOLLOWUP,
    CONF_CACHE_REFRESH_INTERVAL,
    CONF_CALENDAR_CONTEXT,
    CONF_CANCEL_INTENT_AGENT,
    CONF_CLEAN_RESPONSES,
    CONF_CONFIRM_CRITICAL,
    CONF_DIRECT_ALARM_BACKEND_TIMEOUT_SECONDS,
    CONF_DIRECT_ALARM_ENABLE_NOTIFICATION,
    CONF_DIRECT_ALARM_ENABLE_NOTIFY,
    CONF_DIRECT_ALARM_ENABLE_SCRIPT,
    CONF_DIRECT_ALARM_ENABLE_TTS,
    CONF_DIRECT_ALARM_NOTIFY_SERVICE,
    CONF_DIRECT_ALARM_SCRIPT_ENTITY_ID,
    CONF_DIRECT_ALARM_TTS_SERVICE,
    CONF_DIRECT_ALARM_TTS_TARGET,
    CONF_ENABLE_CACHE_WARMING,
    CONF_ENABLE_MEMORY,
    CONF_ENABLE_REQUEST_HISTORY_CONTENT,
    CONF_ENABLE_AGENT_MEMORY,
    CONF_ENABLE_PRESENCE_HEURISTIC,
    CONF_ENABLE_WEB_SEARCH,
    CONF_ENTITY_DISCOVERY_MODE,
    CONF_EXPOSED_ONLY,
    CONF_GROQ_API_KEY,
    CONF_LANGUAGE,
    CONF_HISTORY_REDACT_PATTERNS,
    CONF_HISTORY_RETENTION_DAYS,
    CONF_LLM_PROVIDER,
    CONF_MAX_HISTORY,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_OLLAMA_KEEP_ALIVE,
    CONF_OLLAMA_MODEL,
    CONF_OLLAMA_NUM_CTX,
    CONF_OLLAMA_TIMEOUT,
    CONF_OLLAMA_URL,
    CONF_PROVIDER,
    CONF_TASK_ALLOW_CONTROL,
    CONF_TASK_ALLOW_LOCK_CONTROL,
    CONF_TASK_ENABLE_CACHE_WARMING,
    CONF_TASK_SYSTEM_PROMPT,
    CONF_TOOL_LATENCY_BUDGET_MS,
    CONF_TOOL_MAX_RETRIES,
    CONF_TEMPERATURE,
    CONF_USER_SYSTEM_PROMPT,
    DEFAULT_ASK_FOLLOWUP,
    DEFAULT_ALARM_EXECUTION_MODE,
    DEFAULT_CACHE_REFRESH_INTERVAL,
    DEFAULT_CALENDAR_CONTEXT,
    DEFAULT_CANCEL_INTENT_AGENT,
    DEFAULT_CLEAN_RESPONSES,
    DEFAULT_CONFIRM_CRITICAL,
    DEFAULT_DIRECT_ALARM_BACKEND_TIMEOUT_SECONDS,
    DEFAULT_DIRECT_ALARM_ENABLE_NOTIFICATION,
    DEFAULT_DIRECT_ALARM_ENABLE_NOTIFY,
    DEFAULT_DIRECT_ALARM_ENABLE_SCRIPT,
    DEFAULT_DIRECT_ALARM_ENABLE_TTS,
    DEFAULT_DIRECT_ALARM_NOTIFY_SERVICE,
    DEFAULT_DIRECT_ALARM_SCRIPT_ENTITY_ID,
    DEFAULT_DIRECT_ALARM_TTS_SERVICE,
    DEFAULT_DIRECT_ALARM_TTS_TARGET,
    DEFAULT_ENABLE_CACHE_WARMING,
    DEFAULT_ENABLE_MEMORY,
    DEFAULT_ENABLE_REQUEST_HISTORY_CONTENT,
    DEFAULT_ENABLE_AGENT_MEMORY,
    DEFAULT_ENABLE_PRESENCE_HEURISTIC,
    DEFAULT_ENTITY_DISCOVERY_MODE,
    DEFAULT_EXPOSED_ONLY,
    DEFAULT_HISTORY_REDACT_PATTERNS,
    DEFAULT_HISTORY_RETENTION_DAYS,
    DEFAULT_MAX_HISTORY,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TASK_ALLOW_CONTROL,
    DEFAULT_TASK_ALLOW_LOCK_CONTROL,
    DEFAULT_TASK_ENABLE_CACHE_WARMING,
    DEFAULT_TASK_SYSTEM_PROMPT,
    DEFAULT_TOOL_LATENCY_BUDGET_MS,
    DEFAULT_TOOL_MAX_RETRIES,
    DEFAULT_TEMPERATURE,
    DEFAULT_USER_SYSTEM_PROMPT,
    LLM_PROVIDER_GROQ,
    LLM_PROVIDER_OLLAMA,
    LLM_PROVIDER_OPENROUTER,
    LLM_PROVIDERS,
    OLLAMA_DEFAULT_KEEP_ALIVE,
    OLLAMA_DEFAULT_MODEL,
    OLLAMA_DEFAULT_NUM_CTX,
    OLLAMA_DEFAULT_TIMEOUT,
    OLLAMA_DEFAULT_URL,
    TOOL_LATENCY_BUDGET_MS_MAX,
    TOOL_LATENCY_BUDGET_MS_MIN,
    TOOL_MAX_RETRIES_MAX,
    TOOL_MAX_RETRIES_MIN,
    DIRECT_ALARM_BACKEND_TIMEOUT_MIN,
    DIRECT_ALARM_BACKEND_TIMEOUT_MAX,
)

_LOGGER = logging.getLogger(__name__)


class SmartAssistSubentryFlowHandler(ConfigSubentryFlow):
    """Base class for Smart Assist subentry flows."""
    
    def _get_api_key(self) -> str:
        """Get OpenRouter API key from parent config entry."""
        return self._get_entry().data.get(CONF_API_KEY, "")
    
    def _get_groq_api_key(self) -> str:
        """Get Groq API key from parent config entry."""
        entry = self._get_entry()
        groq_key = entry.data.get(CONF_GROQ_API_KEY, "")
        if not groq_key:
            # Fallback: try old API key location for backwards compatibility
            groq_key = entry.data.get(CONF_API_KEY, "")
            if groq_key:
                _LOGGER.debug("Using legacy API key location for Groq")
        return groq_key
    
    def _get_ollama_config(self) -> dict[str, Any]:
        """Get Ollama configuration from parent config entry."""
        entry = self._get_entry()
        return {
            CONF_OLLAMA_URL: entry.data.get(CONF_OLLAMA_URL, OLLAMA_DEFAULT_URL),
            CONF_OLLAMA_MODEL: entry.data.get(CONF_OLLAMA_MODEL, OLLAMA_DEFAULT_MODEL),
            CONF_OLLAMA_KEEP_ALIVE: entry.data.get(CONF_OLLAMA_KEEP_ALIVE, OLLAMA_DEFAULT_KEEP_ALIVE),
            CONF_OLLAMA_NUM_CTX: entry.data.get(CONF_OLLAMA_NUM_CTX, OLLAMA_DEFAULT_NUM_CTX),
            CONF_OLLAMA_TIMEOUT: entry.data.get(CONF_OLLAMA_TIMEOUT, OLLAMA_DEFAULT_TIMEOUT),
        }
    
    def _is_ollama_configured(self) -> bool:
        """Check if Ollama is configured in the parent config entry."""
        entry = self._get_entry()
        return bool(entry.data.get(CONF_OLLAMA_URL))
    
    async def _fetch_models(self, llm_provider: str = LLM_PROVIDER_OPENROUTER) -> list[dict[str, str]]:
        """Fetch available models based on LLM provider."""
        if llm_provider == LLM_PROVIDER_GROQ:
            return await fetch_groq_models(self._get_groq_api_key())
        elif llm_provider == LLM_PROVIDER_OLLAMA:
            ollama_config = self._get_ollama_config()
            return await fetch_ollama_models(ollama_config[CONF_OLLAMA_URL])
        return await fetch_openrouter_models(self._get_api_key())
    
    async def _fetch_providers(self, model_id: str) -> list[dict[str, str]]:
        """Fetch available providers for a model (OpenRouter only)."""
        return await fetch_model_providers(self._get_api_key(), model_id)


class ConversationFlowHandler(SmartAssistSubentryFlowHandler):
    """Handle subentry flow for Conversation Agents.
    
    Flow steps:
    1. user: LLM Provider selection (based on configured keys)
    2. model: Model selection based on provider
    3. settings: Provider routing (OpenRouter only) + all behavior settings
    4. prompt: System prompt customization
    """
    
    def __init__(self) -> None:
        """Initialize the flow handler."""
        super().__init__()
        self._data: dict[str, Any] = {}
        self._available_models: list[dict[str, str]] | None = None
        self._available_providers: list[dict[str, str]] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle first step - LLM Provider selection."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            llm_provider = user_input.get(CONF_LLM_PROVIDER, LLM_PROVIDER_GROQ)
            self._data[CONF_LLM_PROVIDER] = llm_provider
            
            if not errors:
                return await self.async_step_model()
        
        # Check which API keys/providers are already configured
        has_openrouter_key = bool(self._get_api_key())
        has_groq_key = bool(self._get_groq_api_key())
        has_ollama = self._is_ollama_configured()
        
        # Build provider options based on configured providers
        llm_provider_options = []
        if has_groq_key:
            llm_provider_options.append(
                {"value": LLM_PROVIDER_GROQ, "label": LLM_PROVIDERS[LLM_PROVIDER_GROQ]}
            )
        if has_openrouter_key:
            llm_provider_options.append(
                {"value": LLM_PROVIDER_OPENROUTER, "label": LLM_PROVIDERS[LLM_PROVIDER_OPENROUTER]}
            )
        if has_ollama:
            llm_provider_options.append(
                {"value": LLM_PROVIDER_OLLAMA, "label": LLM_PROVIDERS[LLM_PROVIDER_OLLAMA]}
            )
        
        # If only one provider is configured, skip selection and go directly to model
        if len(llm_provider_options) == 1:
            self._data[CONF_LLM_PROVIDER] = llm_provider_options[0]["value"]
            return await self.async_step_model()
        
        # If no providers configured, show error
        if not llm_provider_options:
            return self.async_abort(reason="no_api_keys_configured")
        
        # Default to Groq if available, then Ollama, then OpenRouter
        if has_groq_key:
            default_provider = LLM_PROVIDER_GROQ
        elif has_ollama:
            default_provider = LLM_PROVIDER_OLLAMA
        else:
            default_provider = LLM_PROVIDER_OPENROUTER
        
        schema_dict = {
            vol.Required(CONF_LLM_PROVIDER, default=default_provider): SelectSelector(
                SelectSelectorConfig(
                    options=llm_provider_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle model selection step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_settings()
        
        # Fetch models based on selected LLM provider
        llm_provider = self._data.get(CONF_LLM_PROVIDER, LLM_PROVIDER_OPENROUTER)
        if self._available_models is None:
            self._available_models = await self._fetch_models(llm_provider)
        
        # Determine default model based on provider
        if llm_provider == LLM_PROVIDER_OLLAMA:
            ollama_config = self._get_ollama_config()
            default_model = ollama_config.get(CONF_OLLAMA_MODEL, OLLAMA_DEFAULT_MODEL)
        else:
            default_model = DEFAULT_MODEL
        
        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL, default=default_model): SelectSelector(
                        SelectSelectorConfig(
                            options=self._available_models,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                }
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle settings step - provider + all other settings."""
        errors: dict[str, str] = {}
        if user_input is not None and not errors:
            self._data.update(user_input)
            return await self.async_step_prompt()
        
        llm_provider = self._data.get(CONF_LLM_PROVIDER, LLM_PROVIDER_OPENROUTER)
        
        # Build settings schema - provider routing only for OpenRouter
        schema_dict: dict[Any, Any] = {}
        
        if llm_provider == LLM_PROVIDER_OPENROUTER:
            # Fetch providers for the selected model (OpenRouter only)
            model_id = self._data.get(CONF_MODEL, DEFAULT_MODEL)
            if self._available_providers is None:
                self._available_providers = await self._fetch_providers(model_id)
            
            schema_dict[vol.Required(CONF_PROVIDER, default=DEFAULT_PROVIDER)] = SelectSelector(
                SelectSelectorConfig(
                    options=self._available_providers,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        
        # Common settings for both providers
        # Group: LLM Settings
        schema_dict.update({
            vol.Required(CONF_TEMPERATURE, default=DEFAULT_TEMPERATURE): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.1, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS): NumberSelector(
                NumberSelectorConfig(min=100, max=4000, step=100, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(CONF_MAX_HISTORY, default=DEFAULT_MAX_HISTORY): NumberSelector(
                NumberSelectorConfig(min=1, max=20, step=1, mode=NumberSelectorMode.SLIDER)
            ),
            # Group: Response Behavior
            vol.Optional(CONF_LANGUAGE, default="auto"): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Required(CONF_CLEAN_RESPONSES, default=DEFAULT_CLEAN_RESPONSES): BooleanSelector(),
            vol.Required(CONF_ASK_FOLLOWUP, default=DEFAULT_ASK_FOLLOWUP): BooleanSelector(),
            # Group: Entity Control
            vol.Required(CONF_EXPOSED_ONLY, default=DEFAULT_EXPOSED_ONLY): BooleanSelector(),
            vol.Required(CONF_ENTITY_DISCOVERY_MODE, default=DEFAULT_ENTITY_DISCOVERY_MODE): SelectSelector(
                SelectSelectorConfig(options=["full_index", "smart_discovery"], mode=SelectSelectorMode.DROPDOWN, translation_key="entity_discovery_mode")
            ),
            vol.Required(CONF_CONFIRM_CRITICAL, default=DEFAULT_CONFIRM_CRITICAL): BooleanSelector(),
            vol.Required(CONF_TOOL_MAX_RETRIES, default=DEFAULT_TOOL_MAX_RETRIES): NumberSelector(
                NumberSelectorConfig(
                    min=TOOL_MAX_RETRIES_MIN,
                    max=TOOL_MAX_RETRIES_MAX,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(CONF_TOOL_LATENCY_BUDGET_MS, default=DEFAULT_TOOL_LATENCY_BUDGET_MS): NumberSelector(
                NumberSelectorConfig(
                    min=TOOL_LATENCY_BUDGET_MS_MIN,
                    max=TOOL_LATENCY_BUDGET_MS_MAX,
                    step=500,
                    unit_of_measurement="ms",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            # Group: Features
            vol.Required(CONF_ENABLE_WEB_SEARCH, default=True): BooleanSelector(),
            vol.Required(CONF_CALENDAR_CONTEXT, default=DEFAULT_CALENDAR_CONTEXT): BooleanSelector(),
            # Group: Memory & Personalization
            vol.Required(CONF_ENABLE_MEMORY, default=DEFAULT_ENABLE_MEMORY): BooleanSelector(),
            vol.Required(CONF_ENABLE_AGENT_MEMORY, default=DEFAULT_ENABLE_AGENT_MEMORY): BooleanSelector(),
            vol.Required(CONF_ENABLE_PRESENCE_HEURISTIC, default=DEFAULT_ENABLE_PRESENCE_HEURISTIC): BooleanSelector(),
            vol.Required(
                CONF_ENABLE_REQUEST_HISTORY_CONTENT,
                default=DEFAULT_ENABLE_REQUEST_HISTORY_CONTENT,
            ): BooleanSelector(),
            vol.Required(
                CONF_HISTORY_RETENTION_DAYS,
                default=DEFAULT_HISTORY_RETENTION_DAYS,
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=365, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_HISTORY_REDACT_PATTERNS,
                default=DEFAULT_HISTORY_REDACT_PATTERNS,
            ): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
            ),
            # Group: Performance
            vol.Required(CONF_ENABLE_CACHE_WARMING, default=DEFAULT_ENABLE_CACHE_WARMING): BooleanSelector(),
            vol.Required(CONF_CACHE_REFRESH_INTERVAL, default=DEFAULT_CACHE_REFRESH_INTERVAL): NumberSelector(
                NumberSelectorConfig(min=1, max=55, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX)
            ),
            # Group: Cancel Intent
            vol.Required(CONF_CANCEL_INTENT_AGENT, default=DEFAULT_CANCEL_INTENT_AGENT): BooleanSelector(),
        })
        
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_prompt(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle prompt configuration step."""
        if user_input is not None:
            self._data.update(user_input)
            
            # Generate title from model name
            model = self._data.get(CONF_MODEL, DEFAULT_MODEL)
            model_short = model.split("/")[-1] if "/" in model else model
            title = f"{model_short} Agent"
            
            return self.async_create_entry(
                title=title,
                data=self._data,
            )
        
        return self.async_show_form(
            step_id="prompt",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USER_SYSTEM_PROMPT, default=DEFAULT_USER_SYSTEM_PROMPT
                    ): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                            multiline=True,
                        )
                    ),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration step 1 - LLM provider selection."""
        # Pre-fill with existing values on first call
        if not self._data:
            self._data = dict(self._get_reconfigure_subentry().data)
            # Remove any API keys from subentry data - they should only be in parent entry
            self._data.pop(CONF_GROQ_API_KEY, None)
            self._data.pop(CONF_API_KEY, None)
        
        errors: dict[str, str] = {}
        
        if user_input is not None:
            llm_provider = user_input.get(CONF_LLM_PROVIDER, LLM_PROVIDER_GROQ)
            self._data[CONF_LLM_PROVIDER] = llm_provider
            
            # Validate API key/configuration availability for selected provider
            if llm_provider == LLM_PROVIDER_GROQ:
                if not self._get_groq_api_key():
                    errors["base"] = "groq_api_key_required"
            elif llm_provider == LLM_PROVIDER_OPENROUTER:
                if not self._get_api_key():
                    errors["base"] = "openrouter_api_key_required"
            elif llm_provider == LLM_PROVIDER_OLLAMA:
                if not self._is_ollama_configured():
                    errors["base"] = "ollama_not_configured"
            
            if not errors:
                # Reset models so they get refetched for new provider
                self._available_models = None
                self._available_providers = None
                return await self.async_step_reconfigure_model()
        
        # Build provider options based on configured API keys/providers
        has_groq_key = bool(self._get_groq_api_key())
        has_openrouter_key = bool(self._get_api_key())
        has_ollama = self._is_ollama_configured()
        
        llm_provider_options = []
        if has_groq_key:
            llm_provider_options.append(
                {"value": LLM_PROVIDER_GROQ, "label": LLM_PROVIDERS[LLM_PROVIDER_GROQ]}
            )
        if has_openrouter_key:
            llm_provider_options.append(
                {"value": LLM_PROVIDER_OPENROUTER, "label": LLM_PROVIDERS[LLM_PROVIDER_OPENROUTER]}
            )
        if has_ollama:
            llm_provider_options.append(
                {"value": LLM_PROVIDER_OLLAMA, "label": LLM_PROVIDERS[LLM_PROVIDER_OLLAMA]}
            )
        
        # If no providers configured, abort
        if not llm_provider_options:
            return self.async_abort(reason="no_api_keys_configured")
        
        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_LLM_PROVIDER): SelectSelector(
                SelectSelectorConfig(
                    options=llm_provider_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
        
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema_dict),
                self._data,
            ),
            errors=errors,
        )

    async def async_step_reconfigure_model(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration step 2 - model selection."""
        if user_input is not None:
            self._data[CONF_MODEL] = user_input[CONF_MODEL]
            self._available_providers = None
            return await self.async_step_reconfigure_settings()
        
        # Fetch models for dropdown based on LLM provider
        llm_provider = self._data.get(CONF_LLM_PROVIDER, LLM_PROVIDER_OPENROUTER)
        if self._available_models is None:
            self._available_models = await self._fetch_models(llm_provider)
        
        # Ensure current model is in the list
        model_options = list(self._available_models)
        current_model = self._data.get(CONF_MODEL, DEFAULT_MODEL)
        model_ids = [m["value"] for m in model_options]
        if current_model not in model_ids:
            model_options.insert(0, {"value": current_model, "label": f"{current_model} (current)"})
        
        return self.async_show_form(
            step_id="reconfigure_model",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_MODEL): SelectSelector(
                            SelectSelectorConfig(
                                options=model_options,
                                mode=SelectSelectorMode.DROPDOWN,
                                custom_value=True,
                            )
                        ),
                    }
                ),
                self._data,
            ),
        )

    async def async_step_reconfigure_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration step 3 - provider routing and all settings."""
        errors: dict[str, str] = {}
        if user_input is not None and not errors:
            self._data.update(user_input)
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=self._data,
            )
        
        llm_provider = self._data.get(CONF_LLM_PROVIDER, LLM_PROVIDER_OPENROUTER)
        
        schema_dict: dict[Any, Any] = {}
        
        # Provider routing only for OpenRouter
        if llm_provider == LLM_PROVIDER_OPENROUTER:
            model_id = self._data.get(CONF_MODEL, DEFAULT_MODEL)
            if self._available_providers is None:
                self._available_providers = await self._fetch_providers(model_id)
            
            provider_options = list(self._available_providers)
            current_provider = self._data.get(CONF_PROVIDER, DEFAULT_PROVIDER)
            provider_values = [p["value"] for p in provider_options]
            if current_provider not in provider_values:
                provider_options.insert(0, {"value": current_provider, "label": f"{current_provider} (current)"})
            
            schema_dict[vol.Required(CONF_PROVIDER)] = SelectSelector(
                SelectSelectorConfig(
                    options=provider_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        
        # Common settings
        # Group: LLM Settings
        schema_dict.update({
            vol.Required(CONF_TEMPERATURE): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.1, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(CONF_MAX_TOKENS): NumberSelector(
                NumberSelectorConfig(min=100, max=4000, step=100, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(CONF_MAX_HISTORY): NumberSelector(
                NumberSelectorConfig(min=1, max=20, step=1, mode=NumberSelectorMode.SLIDER)
            ),
            # Group: Response Behavior
            vol.Optional(CONF_LANGUAGE): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Required(CONF_CLEAN_RESPONSES): BooleanSelector(),
            vol.Required(CONF_ASK_FOLLOWUP): BooleanSelector(),
            # Group: Entity Control
            vol.Required(CONF_EXPOSED_ONLY): BooleanSelector(),
            vol.Required(CONF_ENTITY_DISCOVERY_MODE): SelectSelector(
                SelectSelectorConfig(options=["full_index", "smart_discovery"], mode=SelectSelectorMode.DROPDOWN, translation_key="entity_discovery_mode")
            ),
            vol.Required(CONF_CONFIRM_CRITICAL): BooleanSelector(),
            vol.Required(CONF_TOOL_MAX_RETRIES): NumberSelector(
                NumberSelectorConfig(
                    min=TOOL_MAX_RETRIES_MIN,
                    max=TOOL_MAX_RETRIES_MAX,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(CONF_TOOL_LATENCY_BUDGET_MS): NumberSelector(
                NumberSelectorConfig(
                    min=TOOL_LATENCY_BUDGET_MS_MIN,
                    max=TOOL_LATENCY_BUDGET_MS_MAX,
                    step=500,
                    unit_of_measurement="ms",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            # Group: Features
            vol.Required(CONF_ENABLE_WEB_SEARCH): BooleanSelector(),
            vol.Required(CONF_CALENDAR_CONTEXT): BooleanSelector(),
            # Group: Memory & Personalization
            vol.Required(CONF_ENABLE_MEMORY): BooleanSelector(),
            vol.Required(CONF_ENABLE_AGENT_MEMORY): BooleanSelector(),
            vol.Required(CONF_ENABLE_PRESENCE_HEURISTIC): BooleanSelector(),
            vol.Required(
                CONF_ENABLE_REQUEST_HISTORY_CONTENT,
                default=DEFAULT_ENABLE_REQUEST_HISTORY_CONTENT,
            ): BooleanSelector(),
            vol.Required(
                CONF_HISTORY_RETENTION_DAYS,
                default=DEFAULT_HISTORY_RETENTION_DAYS,
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=365, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_HISTORY_REDACT_PATTERNS,
                default=DEFAULT_HISTORY_REDACT_PATTERNS,
            ): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
            ),
            # Group: Performance
            vol.Required(CONF_ENABLE_CACHE_WARMING): BooleanSelector(),
            vol.Required(CONF_CACHE_REFRESH_INTERVAL): NumberSelector(
                NumberSelectorConfig(min=1, max=55, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX)
            ),
            # Cancel Intent
            vol.Required(CONF_CANCEL_INTENT_AGENT): BooleanSelector(),
        })
        schema_dict.update({
            # System Prompt
            vol.Required(CONF_USER_SYSTEM_PROMPT): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
            ),
        })
        
        return self.async_show_form(
            step_id="reconfigure_settings",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema_dict),
                self._data,
            ),
            errors=errors,
        )


class AITaskFlowHandler(SmartAssistSubentryFlowHandler):
    """Handle subentry flow for AI Tasks.
    
    Flow steps:
    1. user: LLM Provider selection (based on configured keys)
    2. model: Model selection based on provider
    3. settings: Provider routing (OpenRouter only) + all other settings
    """
    
    def __init__(self) -> None:
        """Initialize the flow handler."""
        super().__init__()
        self._data: dict[str, Any] = {}
        self._available_models: list[dict[str, str]] | None = None
        self._available_providers: list[dict[str, str]] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle first step - LLM Provider selection."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            llm_provider = user_input.get(CONF_LLM_PROVIDER, LLM_PROVIDER_GROQ)
            self._data[CONF_LLM_PROVIDER] = llm_provider
            
            if not errors:
                return await self.async_step_model()
        
        # Check which API keys/providers are already configured
        has_openrouter_key = bool(self._get_api_key())
        has_groq_key = bool(self._get_groq_api_key())
        has_ollama = self._is_ollama_configured()
        
        # Build provider options based on configured providers
        llm_provider_options = []
        if has_groq_key:
            llm_provider_options.append(
                {"value": LLM_PROVIDER_GROQ, "label": LLM_PROVIDERS[LLM_PROVIDER_GROQ]}
            )
        if has_openrouter_key:
            llm_provider_options.append(
                {"value": LLM_PROVIDER_OPENROUTER, "label": LLM_PROVIDERS[LLM_PROVIDER_OPENROUTER]}
            )
        if has_ollama:
            llm_provider_options.append(
                {"value": LLM_PROVIDER_OLLAMA, "label": LLM_PROVIDERS[LLM_PROVIDER_OLLAMA]}
            )
        
        # If only one provider is configured, skip selection and go directly to model
        if len(llm_provider_options) == 1:
            self._data[CONF_LLM_PROVIDER] = llm_provider_options[0]["value"]
            return await self.async_step_model()
        
        # If no providers configured, show error
        if not llm_provider_options:
            return self.async_abort(reason="no_api_keys_configured")
        
        # Default to Groq if available, then Ollama, then OpenRouter
        if has_groq_key:
            default_provider = LLM_PROVIDER_GROQ
        elif has_ollama:
            default_provider = LLM_PROVIDER_OLLAMA
        else:
            default_provider = LLM_PROVIDER_OPENROUTER
        
        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_LLM_PROVIDER, default=default_provider): SelectSelector(
                SelectSelectorConfig(
                    options=llm_provider_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle model selection step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_settings()
        
        llm_provider = self._data.get(CONF_LLM_PROVIDER, LLM_PROVIDER_OPENROUTER)
        if self._available_models is None:
            self._available_models = await self._fetch_models(llm_provider)
        
        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL, default=DEFAULT_MODEL): SelectSelector(
                        SelectSelectorConfig(
                            options=self._available_models,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                }
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle settings step - provider + all other settings."""
        if user_input is not None:
            self._data.update(user_input)
            
            # Generate title from model name
            model = self._data.get(CONF_MODEL, DEFAULT_MODEL)
            model_short = model.split("/")[-1] if "/" in model else model
            title = f"{model_short} Task"
            
            return self.async_create_entry(
                title=title,
                data=self._data,
            )
        
        llm_provider = self._data.get(CONF_LLM_PROVIDER, LLM_PROVIDER_OPENROUTER)
        
        schema_dict: dict[Any, Any] = {}
        
        if llm_provider == LLM_PROVIDER_OPENROUTER:
            model_id = self._data.get(CONF_MODEL, DEFAULT_MODEL)
            if self._available_providers is None:
                self._available_providers = await self._fetch_providers(model_id)
            
            schema_dict[vol.Required(CONF_PROVIDER, default=DEFAULT_PROVIDER)] = SelectSelector(
                SelectSelectorConfig(
                    options=self._available_providers,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        
        schema_dict.update({
            vol.Required(CONF_TEMPERATURE, default=DEFAULT_TEMPERATURE): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.1, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS): NumberSelector(
                NumberSelectorConfig(min=100, max=4000, step=100, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Optional(CONF_LANGUAGE, default="auto"): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Required(CONF_EXPOSED_ONLY, default=DEFAULT_EXPOSED_ONLY): BooleanSelector(),
            vol.Required(CONF_TOOL_MAX_RETRIES, default=DEFAULT_TOOL_MAX_RETRIES): NumberSelector(
                NumberSelectorConfig(
                    min=TOOL_MAX_RETRIES_MIN,
                    max=TOOL_MAX_RETRIES_MAX,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(CONF_TOOL_LATENCY_BUDGET_MS, default=DEFAULT_TOOL_LATENCY_BUDGET_MS): NumberSelector(
                NumberSelectorConfig(
                    min=TOOL_LATENCY_BUDGET_MS_MIN,
                    max=TOOL_LATENCY_BUDGET_MS_MAX,
                    step=500,
                    unit_of_measurement="ms",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(CONF_TASK_ALLOW_CONTROL, default=DEFAULT_TASK_ALLOW_CONTROL): BooleanSelector(),
            vol.Required(CONF_TASK_ALLOW_LOCK_CONTROL, default=DEFAULT_TASK_ALLOW_LOCK_CONTROL): BooleanSelector(),
            vol.Required(CONF_TASK_SYSTEM_PROMPT, default=DEFAULT_TASK_SYSTEM_PROMPT): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
            ),
            vol.Required(CONF_TASK_ENABLE_CACHE_WARMING, default=DEFAULT_TASK_ENABLE_CACHE_WARMING): BooleanSelector(),
        })
        
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(schema_dict),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration step 1 - LLM provider selection."""
        if not self._data:
            self._data = dict(self._get_reconfigure_subentry().data)
            # Remove any API keys from subentry data - they should only be in parent entry
            self._data.pop(CONF_GROQ_API_KEY, None)
            self._data.pop(CONF_API_KEY, None)
        
        errors: dict[str, str] = {}
        
        if user_input is not None:
            llm_provider = user_input.get(CONF_LLM_PROVIDER, LLM_PROVIDER_OPENROUTER)
            self._data[CONF_LLM_PROVIDER] = llm_provider
            
            # If Groq selected, validate the API key if provided (but don't store in subentry)
            if llm_provider == LLM_PROVIDER_GROQ:
                groq_key = user_input.get(CONF_GROQ_API_KEY, "")
                if groq_key:
                    if not await validate_groq_api_key(groq_key):
                        errors["base"] = "invalid_groq_api_key"
                    # Note: New API key would need parent entry update, not supported in subentry reconfigure
                else:
                    stored_key = self._get_groq_api_key()
                    if not stored_key:
                        errors["base"] = "groq_api_key_required"
            
            if not errors:
                self._available_models = None
                self._available_providers = None
                return await self.async_step_reconfigure_model()
        
        has_groq_key = bool(self._get_groq_api_key())
        
        llm_provider_options = [
            {"value": LLM_PROVIDER_OPENROUTER, "label": LLM_PROVIDERS[LLM_PROVIDER_OPENROUTER]},
            {"value": LLM_PROVIDER_GROQ, "label": LLM_PROVIDERS[LLM_PROVIDER_GROQ]},
        ]
        
        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_LLM_PROVIDER): SelectSelector(
                SelectSelectorConfig(
                    options=llm_provider_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
        
        if not has_groq_key:
            schema_dict[vol.Optional(CONF_GROQ_API_KEY, default="")] = TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            )
        
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema_dict),
                self._data,
            ),
            errors=errors,
        )

    async def async_step_reconfigure_model(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration step 2 - model selection."""
        if user_input is not None:
            self._data[CONF_MODEL] = user_input[CONF_MODEL]
            self._available_providers = None
            return await self.async_step_reconfigure_settings()
        
        llm_provider = self._data.get(CONF_LLM_PROVIDER, LLM_PROVIDER_OPENROUTER)
        if self._available_models is None:
            self._available_models = await self._fetch_models(llm_provider)
        
        model_options = list(self._available_models)
        current_model = self._data.get(CONF_MODEL, DEFAULT_MODEL)
        model_ids = [m["value"] for m in model_options]
        if current_model not in model_ids:
            model_options.insert(0, {"value": current_model, "label": f"{current_model} (current)"})
        
        return self.async_show_form(
            step_id="reconfigure_model",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_MODEL): SelectSelector(
                            SelectSelectorConfig(
                                options=model_options,
                                mode=SelectSelectorMode.DROPDOWN,
                                custom_value=True,
                            )
                        ),
                    }
                ),
                self._data,
            ),
        )

    async def async_step_reconfigure_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration step 3 - provider routing and all settings."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=self._data,
            )
        
        llm_provider = self._data.get(CONF_LLM_PROVIDER, LLM_PROVIDER_OPENROUTER)
        
        schema_dict: dict[Any, Any] = {}
        
        if llm_provider == LLM_PROVIDER_OPENROUTER:
            model_id = self._data.get(CONF_MODEL, DEFAULT_MODEL)
            if self._available_providers is None:
                self._available_providers = await self._fetch_providers(model_id)
            
            provider_options = list(self._available_providers)
            current_provider = self._data.get(CONF_PROVIDER, DEFAULT_PROVIDER)
            provider_values = [p["value"] for p in provider_options]
            if current_provider not in provider_values:
                provider_options.insert(0, {"value": current_provider, "label": f"{current_provider} (current)"})
            
            schema_dict[vol.Required(CONF_PROVIDER)] = SelectSelector(
                SelectSelectorConfig(
                    options=provider_options,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        
        schema_dict.update({
            vol.Required(CONF_TEMPERATURE): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.1, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(CONF_MAX_TOKENS): NumberSelector(
                NumberSelectorConfig(min=100, max=4000, step=100, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Optional(CONF_LANGUAGE): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Required(CONF_EXPOSED_ONLY): BooleanSelector(),
            vol.Required(CONF_TOOL_MAX_RETRIES): NumberSelector(
                NumberSelectorConfig(
                    min=TOOL_MAX_RETRIES_MIN,
                    max=TOOL_MAX_RETRIES_MAX,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(CONF_TOOL_LATENCY_BUDGET_MS): NumberSelector(
                NumberSelectorConfig(
                    min=TOOL_LATENCY_BUDGET_MS_MIN,
                    max=TOOL_LATENCY_BUDGET_MS_MAX,
                    step=500,
                    unit_of_measurement="ms",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(CONF_TASK_ALLOW_CONTROL): BooleanSelector(),
            vol.Required(CONF_TASK_ALLOW_LOCK_CONTROL): BooleanSelector(),
            vol.Required(CONF_TASK_SYSTEM_PROMPT): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
            ),
            vol.Required(CONF_TASK_ENABLE_CACHE_WARMING): BooleanSelector(),
        })
        
        return self.async_show_form(
            step_id="reconfigure_settings",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema_dict),
                self._data,
            ),
        )
