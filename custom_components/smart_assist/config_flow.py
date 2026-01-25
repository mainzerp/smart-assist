"""Config flow for Smart Assist integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
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

from .const import (
    CONF_API_KEY,
    CONF_ASK_FOLLOWUP,
    CONF_CACHE_REFRESH_INTERVAL,
    CONF_CACHE_TTL_EXTENDED,
    CONF_CLEAN_RESPONSES,
    CONF_CONFIRM_CRITICAL,
    CONF_ENABLE_CACHE_WARMING,
    CONF_ENABLE_PROMPT_CACHING,
    CONF_ENABLE_QUICK_ACTIONS,
    CONF_ENABLE_WEB_SEARCH,
    CONF_EXPOSED_ONLY,
    CONF_LANGUAGE,
    CONF_MAX_HISTORY,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_PROVIDER,
    CONF_TEMPERATURE,
    CONF_USER_SYSTEM_PROMPT,
    DEFAULT_ASK_FOLLOWUP,
    DEFAULT_CACHE_REFRESH_INTERVAL,
    DEFAULT_CACHE_TTL_EXTENDED,
    DEFAULT_CLEAN_RESPONSES,
    DEFAULT_ENABLE_CACHE_WARMING,
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_HISTORY,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TEMPERATURE,
    DEFAULT_USER_SYSTEM_PROMPT,
    DOMAIN,
    OPENROUTER_API_URL,
    PROVIDERS,
    supports_prompt_caching,
)

_LOGGER = logging.getLogger(__name__)


async def validate_api_key(api_key: str) -> bool:
    """Validate the OpenRouter API key."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://openrouter.ai/api/v1/models",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                return response.status == 200
    except (aiohttp.ClientError, TimeoutError):
        return False


async def fetch_openrouter_models(api_key: str) -> list[dict[str, str]]:
    """Fetch available models from OpenRouter API.
    
    Returns list of {"value": model_id, "label": display_name} dicts.
    Falls back to DEFAULT_MODEL on error.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://openrouter.ai/api/v1/models",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    _LOGGER.warning("Failed to fetch models from OpenRouter: %s", response.status)
                    return _get_fallback_models()
                
                data = await response.json()
                models = data.get("data", [])
                
                if not models:
                    return _get_fallback_models()
                
                # Sort by model id and format for selector
                model_options = []
                for model in sorted(models, key=lambda m: m.get("id", "")):
                    model_id = model.get("id", "")
                    name = model.get("name", model_id)
                    # Add pricing info if available
                    pricing = model.get("pricing", {})
                    prompt_price = pricing.get("prompt", "0")
                    try:
                        # Convert to dollars per million tokens
                        price_per_m = float(prompt_price) * 1_000_000
                        if price_per_m > 0:
                            label = f"{model_id} - {name} (${price_per_m:.2f}/M)"
                        else:
                            label = f"{model_id} - {name} (Free)"
                    except (ValueError, TypeError):
                        label = f"{model_id} - {name}"
                    
                    model_options.append({"value": model_id, "label": label})
                
                _LOGGER.debug("Fetched %d models from OpenRouter", len(model_options))
                return model_options
                
    except (aiohttp.ClientError, TimeoutError, Exception) as err:
        _LOGGER.warning("Error fetching models from OpenRouter: %s", err)
        return _get_fallback_models()


def _get_fallback_models() -> list[dict[str, str]]:
    """Get minimal fallback model list when API is unavailable."""
    # Only show default model - user can enter any model manually
    return [
        {"value": DEFAULT_MODEL, "label": f"{DEFAULT_MODEL} (default)"}
    ]


class SmartAssistConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Smart Assist."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._available_models: list[dict[str, str]] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return SmartAssistOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the API configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate API key
            if await validate_api_key(user_input[CONF_API_KEY]):
                self._data.update(user_input)
                return await self.async_step_model()
            errors["base"] = "invalid_api_key"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"docs_url": "https://openrouter.ai/keys"},
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle model selection step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_behavior()

        # Fetch models from OpenRouter (with fallback to static list)
        if self._available_models is None:
            api_key = self._data.get(CONF_API_KEY, "")
            self._available_models = await fetch_openrouter_models(api_key)
        
        model_options = self._available_models

        # Provider options
        provider_options = [
            {"value": provider_id, "label": display_name}
            for provider_id, display_name in PROVIDERS.items()
        ]

        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL, default=DEFAULT_MODEL): SelectSelector(
                        SelectSelectorConfig(
                            options=model_options,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,  # Allow free text entry
                        )
                    ),
                    vol.Required(CONF_PROVIDER, default=DEFAULT_PROVIDER): SelectSelector(
                        SelectSelectorConfig(
                            options=provider_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_TEMPERATURE, default=DEFAULT_TEMPERATURE
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0.0,
                            max=1.0,
                            step=0.1,
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=100,
                            max=4000,
                            step=100,
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                }
            ),
            description_placeholders={
                "caching_docs_url": "https://openrouter.ai/docs/guides/best-practices/prompt-caching"
            },
        )

    async def async_step_behavior(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle behavior settings step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_prompt()

        return self.async_show_form(
            step_id="behavior",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "en", "label": "English"},
                                {"value": "de", "label": "Deutsch"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(CONF_EXPOSED_ONLY, default=True): BooleanSelector(),
                    vol.Required(CONF_CONFIRM_CRITICAL, default=True): BooleanSelector(),
                    vol.Required(
                        CONF_MAX_HISTORY, default=DEFAULT_MAX_HISTORY
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=20,
                            step=1,
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(CONF_ENABLE_WEB_SEARCH, default=True): BooleanSelector(),
                    vol.Required(
                        CONF_ENABLE_QUICK_ACTIONS, default=True
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ENABLE_PROMPT_CACHING, default=True
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_CACHE_TTL_EXTENDED, default=DEFAULT_CACHE_TTL_EXTENDED
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ENABLE_CACHE_WARMING, default=DEFAULT_ENABLE_CACHE_WARMING
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_CACHE_REFRESH_INTERVAL, default=DEFAULT_CACHE_REFRESH_INTERVAL
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=55,
                            step=1,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_CLEAN_RESPONSES, default=DEFAULT_CLEAN_RESPONSES
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ASK_FOLLOWUP, default=DEFAULT_ASK_FOLLOWUP
                    ): BooleanSelector(),
                }
            ),
        )

    async def async_step_prompt(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle prompt configuration step."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title="Smart Assist",
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


class SmartAssistOptionsFlow(OptionsFlow):
    """Handle options flow for Smart Assist."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self._available_models: list[dict[str, str]] | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.data

        # Fetch models from OpenRouter (with fallback to static list)
        if self._available_models is None:
            api_key = current.get(CONF_API_KEY, "")
            self._available_models = await fetch_openrouter_models(api_key)
        
        model_options = list(self._available_models)  # Make a copy

        # Add current model at top if not in fetched list
        current_model = current.get(CONF_MODEL, DEFAULT_MODEL)
        model_ids = [m["value"] for m in model_options]
        if current_model not in model_ids:
            model_options.insert(0, {"value": current_model, "label": f"{current_model} (current)"})

        # Provider options
        provider_options = [
            {"value": provider_id, "label": display_name}
            for provider_id, display_name in PROVIDERS.items()
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODEL, default=current_model
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=model_options,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,  # Allow free text entry
                        )
                    ),
                    vol.Required(
                        CONF_PROVIDER, default=current.get(CONF_PROVIDER, DEFAULT_PROVIDER)
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=provider_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_TEMPERATURE,
                        default=current.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0.0,
                            max=1.0,
                            step=0.1,
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_MAX_TOKENS,
                        default=current.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=100,
                            max=4000,
                            step=100,
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_LANGUAGE,
                        default=current.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "en", "label": "English"},
                                {"value": "de", "label": "Deutsch"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_EXPOSED_ONLY, default=current.get(CONF_EXPOSED_ONLY, True)
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_CONFIRM_CRITICAL,
                        default=current.get(CONF_CONFIRM_CRITICAL, True),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_MAX_HISTORY,
                        default=current.get(CONF_MAX_HISTORY, DEFAULT_MAX_HISTORY),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=20,
                            step=1,
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_ENABLE_WEB_SEARCH,
                        default=current.get(CONF_ENABLE_WEB_SEARCH, True),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ENABLE_QUICK_ACTIONS,
                        default=current.get(CONF_ENABLE_QUICK_ACTIONS, True),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ENABLE_PROMPT_CACHING,
                        default=current.get(CONF_ENABLE_PROMPT_CACHING, True),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_CACHE_TTL_EXTENDED,
                        default=current.get(CONF_CACHE_TTL_EXTENDED, DEFAULT_CACHE_TTL_EXTENDED),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ENABLE_CACHE_WARMING,
                        default=current.get(CONF_ENABLE_CACHE_WARMING, DEFAULT_ENABLE_CACHE_WARMING),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_CACHE_REFRESH_INTERVAL,
                        default=current.get(CONF_CACHE_REFRESH_INTERVAL, DEFAULT_CACHE_REFRESH_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=55,
                            step=1,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_CLEAN_RESPONSES,
                        default=current.get(CONF_CLEAN_RESPONSES, DEFAULT_CLEAN_RESPONSES),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ASK_FOLLOWUP,
                        default=current.get(CONF_ASK_FOLLOWUP, DEFAULT_ASK_FOLLOWUP),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_USER_SYSTEM_PROMPT,
                        default=current.get(
                            CONF_USER_SYSTEM_PROMPT, DEFAULT_USER_SYSTEM_PROMPT
                        ),
                    ): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                            multiline=True,
                        )
                    ),
                }
            ),
        )
