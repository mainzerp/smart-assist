"""Config flow for Smart Assist integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
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

from .config_subentry_flows import (
    AITaskFlowHandler,
    ConversationFlowHandler,
)
from .config_validators import (
    fetch_ollama_models,
    validate_api_key,
    validate_groq_api_key,
    validate_ollama_connection,
)
from .const import (
    CONF_API_KEY,
    CONF_DEBUG_LOGGING,
    CONF_ENABLE_CANCEL_HANDLER,
    CONF_GROQ_API_KEY,
    CONF_LLM_PROVIDER,
    CONF_OLLAMA_KEEP_ALIVE,
    CONF_OLLAMA_MODEL,
    CONF_OLLAMA_NUM_CTX,
    CONF_OLLAMA_TIMEOUT,
    CONF_OLLAMA_URL,
    DEFAULT_DEBUG_LOGGING,
    DEFAULT_ENABLE_CANCEL_HANDLER,
    DOMAIN,
    LLM_PROVIDER_GROQ,
    LLM_PROVIDER_OLLAMA,
    LLM_PROVIDER_OPENROUTER,
    LLM_PROVIDERS,
    OLLAMA_DEFAULT_KEEP_ALIVE,
    OLLAMA_DEFAULT_MODEL,
    OLLAMA_DEFAULT_NUM_CTX,
    OLLAMA_DEFAULT_TIMEOUT,
    OLLAMA_DEFAULT_URL,
)
from .utils import apply_debug_logging

_LOGGER = logging.getLogger(__name__)


class SmartAssistConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Smart Assist.
    
    Two-step flow:
    1. Select LLM Provider (OpenRouter or Groq)
    2. Enter the API key for the selected provider
    
    After setup, users can add Conversation Agents and AI Tasks via subentries.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        _LOGGER.info("Smart Assist: ConfigFlow.__init__ called")
        self._data: dict[str, Any] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this handler."""
        return {
            "conversation": ConversationFlowHandler,
            "ai_task": AITaskFlowHandler,
        }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return SmartAssistOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle step 1 - LLM Provider selection."""
        _LOGGER.info("Smart Assist: async_step_user called with input: %s", user_input is not None)

        # Check if already configured - only one instance allowed
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            self._data[CONF_LLM_PROVIDER] = user_input[CONF_LLM_PROVIDER]
            return await self.async_step_api_key()

        # Build provider options
        llm_provider_options = [
            {"value": LLM_PROVIDER_OPENROUTER, "label": LLM_PROVIDERS[LLM_PROVIDER_OPENROUTER]},
            {"value": LLM_PROVIDER_GROQ, "label": LLM_PROVIDERS[LLM_PROVIDER_GROQ]},
            {"value": LLM_PROVIDER_OLLAMA, "label": LLM_PROVIDERS[LLM_PROVIDER_OLLAMA]},
        ]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LLM_PROVIDER, default=LLM_PROVIDER_GROQ): SelectSelector(
                        SelectSelectorConfig(
                            options=llm_provider_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle step 2 - API key entry or Ollama configuration for selected provider."""
        errors: dict[str, str] = {}
        llm_provider = self._data.get(CONF_LLM_PROVIDER, LLM_PROVIDER_OPENROUTER)

        try:
            if user_input is not None:
                if llm_provider == LLM_PROVIDER_GROQ:
                    api_key = user_input.get(CONF_GROQ_API_KEY, "").strip()
                    if await validate_groq_api_key(api_key):
                        self._data[CONF_GROQ_API_KEY] = api_key
                        _LOGGER.info("Smart Assist: Groq API key valid, creating entry")
                        return self.async_create_entry(
                            title="Smart Assist",
                            data=self._data,
                        )
                    errors["base"] = "invalid_groq_api_key"
                elif llm_provider == LLM_PROVIDER_OLLAMA:
                    ollama_url = user_input.get(CONF_OLLAMA_URL, OLLAMA_DEFAULT_URL).strip()
                    if await validate_ollama_connection(ollama_url):
                        self._data[CONF_OLLAMA_URL] = ollama_url
                        self._data[CONF_OLLAMA_MODEL] = user_input.get(CONF_OLLAMA_MODEL, OLLAMA_DEFAULT_MODEL)
                        self._data[CONF_OLLAMA_KEEP_ALIVE] = user_input.get(CONF_OLLAMA_KEEP_ALIVE, OLLAMA_DEFAULT_KEEP_ALIVE)
                        self._data[CONF_OLLAMA_NUM_CTX] = user_input.get(CONF_OLLAMA_NUM_CTX, OLLAMA_DEFAULT_NUM_CTX)
                        self._data[CONF_OLLAMA_TIMEOUT] = user_input.get(CONF_OLLAMA_TIMEOUT, OLLAMA_DEFAULT_TIMEOUT)
                        _LOGGER.info("Smart Assist: Ollama connection valid, creating entry")
                        return self.async_create_entry(
                            title="Smart Assist (Ollama)",
                            data=self._data,
                        )
                    errors["base"] = "ollama_connection_failed"
                else:
                    api_key = user_input.get(CONF_API_KEY, "").strip()
                    if await validate_api_key(api_key):
                        self._data[CONF_API_KEY] = api_key
                        _LOGGER.info("Smart Assist: OpenRouter API key valid, creating entry")
                        return self.async_create_entry(
                            title="Smart Assist",
                            data=self._data,
                        )
                    errors["base"] = "invalid_api_key"

            # Show appropriate form based on selected provider
            if llm_provider == LLM_PROVIDER_GROQ:
                schema = vol.Schema({
                    vol.Required(CONF_GROQ_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                })
                placeholders = {"docs_url": "https://console.groq.com/keys"}
            elif llm_provider == LLM_PROVIDER_OLLAMA:
                # Fetch available models for the dropdown
                ollama_url = OLLAMA_DEFAULT_URL
                ollama_models = await fetch_ollama_models(ollama_url)
                
                schema = vol.Schema({
                    vol.Required(CONF_OLLAMA_URL, default=OLLAMA_DEFAULT_URL): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.URL)
                    ),
                    vol.Required(CONF_OLLAMA_MODEL, default=OLLAMA_DEFAULT_MODEL): SelectSelector(
                        SelectSelectorConfig(
                            options=ollama_models,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                    vol.Optional(CONF_OLLAMA_KEEP_ALIVE, default=OLLAMA_DEFAULT_KEEP_ALIVE): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "-1", "label": "Keep loaded (recommended)"},
                                {"value": "5m", "label": "5 minutes"},
                                {"value": "30m", "label": "30 minutes"},
                                {"value": "1h", "label": "1 hour"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_OLLAMA_NUM_CTX, default=OLLAMA_DEFAULT_NUM_CTX): NumberSelector(
                        NumberSelectorConfig(
                            min=1024,
                            max=131072,
                            step=1024,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(CONF_OLLAMA_TIMEOUT, default=OLLAMA_DEFAULT_TIMEOUT): NumberSelector(
                        NumberSelectorConfig(
                            min=30,
                            max=600,
                            step=10,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                })
                placeholders = {"docs_url": "https://ollama.com/download"}
            else:
                schema = vol.Schema({
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                })
                placeholders = {"docs_url": "https://openrouter.ai/keys"}

            return self.async_show_form(
                step_id="api_key",
                data_schema=schema,
                errors=errors,
                description_placeholders=placeholders,
            )
        except Exception as e:
            _LOGGER.exception("Smart Assist: Error in async_step_api_key: %s", e)
            raise

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of API keys and Ollama settings."""
        errors: dict[str, str] = {}
        
        reconfigure_entry = self._get_reconfigure_entry()
        current_groq_key = reconfigure_entry.data.get(CONF_GROQ_API_KEY, "")
        current_openrouter_key = reconfigure_entry.data.get(CONF_API_KEY, "")
        current_ollama_url = reconfigure_entry.data.get(CONF_OLLAMA_URL, "")
        current_ollama_num_ctx = reconfigure_entry.data.get(CONF_OLLAMA_NUM_CTX, OLLAMA_DEFAULT_NUM_CTX)
        current_ollama_keep_alive = reconfigure_entry.data.get(CONF_OLLAMA_KEEP_ALIVE, OLLAMA_DEFAULT_KEEP_ALIVE)
        current_ollama_timeout = reconfigure_entry.data.get(CONF_OLLAMA_TIMEOUT, OLLAMA_DEFAULT_TIMEOUT)
        
        if user_input is not None:
            new_data = dict(reconfigure_entry.data)
            
            # Validate and update Groq API key if provided
            new_groq_key = user_input.get(CONF_GROQ_API_KEY, "").strip()
            if new_groq_key:
                if await validate_groq_api_key(new_groq_key):
                    new_data[CONF_GROQ_API_KEY] = new_groq_key
                else:
                    errors["groq_api_key"] = "invalid_groq_api_key"
            
            # Validate and update OpenRouter API key if provided
            new_openrouter_key = user_input.get(CONF_API_KEY, "").strip()
            if new_openrouter_key:
                if await validate_api_key(new_openrouter_key):
                    new_data[CONF_API_KEY] = new_openrouter_key
                else:
                    errors["api_key"] = "invalid_api_key"
            
            # Validate and update Ollama URL if provided
            new_ollama_url = user_input.get(CONF_OLLAMA_URL, "").strip()
            if new_ollama_url:
                if await validate_ollama_connection(new_ollama_url):
                    new_data[CONF_OLLAMA_URL] = new_ollama_url
                else:
                    errors["ollama_url"] = "ollama_connection_failed"
            
            # Update Ollama settings (no validation needed, they have defaults)
            new_data[CONF_OLLAMA_NUM_CTX] = user_input.get(CONF_OLLAMA_NUM_CTX, current_ollama_num_ctx)
            new_data[CONF_OLLAMA_KEEP_ALIVE] = user_input.get(CONF_OLLAMA_KEEP_ALIVE, current_ollama_keep_alive)
            new_data[CONF_OLLAMA_TIMEOUT] = user_input.get(CONF_OLLAMA_TIMEOUT, current_ollama_timeout)
            
            if not errors:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data=new_data,
                )
        
        # Show form with optional API key fields
        # Mask existing keys to show they are configured
        groq_hint = "(configured)" if current_groq_key else "(not set)"
        openrouter_hint = "(configured)" if current_openrouter_key else "(not set)"
        ollama_hint = f"({current_ollama_url})" if current_ollama_url else "(not set)"
        
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Optional(CONF_GROQ_API_KEY, default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_API_KEY, default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_OLLAMA_URL, default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Optional(CONF_OLLAMA_NUM_CTX, default=current_ollama_num_ctx): NumberSelector(
                    NumberSelectorConfig(min=1024, max=131072, step=1024, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_OLLAMA_KEEP_ALIVE, default=current_ollama_keep_alive): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": "-1", "label": "Forever (keep loaded)"},
                            {"value": "5m", "label": "5 minutes"},
                            {"value": "30m", "label": "30 minutes"},
                            {"value": "1h", "label": "1 hour"},
                            {"value": "0", "label": "Unload immediately"},
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_OLLAMA_TIMEOUT, default=current_ollama_timeout): NumberSelector(
                    NumberSelectorConfig(min=30, max=600, step=30, mode=NumberSelectorMode.BOX)
                ),
            }),
            errors=errors,
            description_placeholders={
                "groq_status": groq_hint,
                "openrouter_status": openrouter_hint,
                "ollama_status": ollama_hint,
            },
        )


# =============================================================================
# OPTIONS FLOW (for global settings like debug logging)
# =============================================================================

class SmartAssistOptionsFlow(OptionsFlow):
    """Handle options flow for Smart Assist (global settings)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options step."""
        if user_input is not None:
            # Apply debug logging setting immediately
            debug_enabled = user_input.get(CONF_DEBUG_LOGGING, DEFAULT_DEBUG_LOGGING)
            apply_debug_logging(debug_enabled)

            # Register/unregister cancel intent handler based on toggle
            cancel_enabled = user_input.get(
                CONF_ENABLE_CANCEL_HANDLER, DEFAULT_ENABLE_CANCEL_HANDLER
            )
            from . import _register_cancel_handler, _unregister_cancel_handler
            if cancel_enabled:
                _register_cancel_handler(self.hass)
            else:
                _unregister_cancel_handler(self.hass)

            return self.async_create_entry(title="", data=user_input)
        
        current = {**self._config_entry.data, **self._config_entry.options}
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DEBUG_LOGGING,
                        default=current.get(CONF_DEBUG_LOGGING, DEFAULT_DEBUG_LOGGING),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ENABLE_CANCEL_HANDLER,
                        default=current.get(
                            CONF_ENABLE_CANCEL_HANDLER,
                            DEFAULT_ENABLE_CANCEL_HANDLER,
                        ),
                    ): BooleanSelector(),
                }
            ),
        )
