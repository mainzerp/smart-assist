"""Config flow for Smart Assist integration."""

from __future__ import annotations

import logging
import traceback
from typing import Any

# Set up logging FIRST, before any other operations
_LOGGER = logging.getLogger(__name__)
_LOGGER.warning("Smart Assist config_flow.py: Module loading started")

try:
    import aiohttp
    import voluptuous as vol
    _LOGGER.warning("Smart Assist config_flow.py: aiohttp and voluptuous imported")
except ImportError as e:
    _LOGGER.error("Smart Assist config_flow.py: Failed to import aiohttp/voluptuous: %s", e)
    raise

try:
    from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
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
    _LOGGER.warning("Smart Assist config_flow.py: HA imports done")
except ImportError as e:
    _LOGGER.error("Smart Assist config_flow.py: Failed to import HA modules: %s", e)
    _LOGGER.error("Traceback: %s", traceback.format_exc())
    raise

try:
    from .const import (
        CONF_API_KEY,
        CONF_ASK_FOLLOWUP,
        CONF_CACHE_REFRESH_INTERVAL,
        CONF_CACHE_TTL_EXTENDED,
        CONF_CLEAN_RESPONSES,
        CONF_CONFIRM_CRITICAL,
        CONF_DEBUG_LOGGING,
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
        DEFAULT_DEBUG_LOGGING,
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
except ImportError as e:
    _LOGGER.error("Smart Assist: Failed to import const module: %s", e)
    _LOGGER.error("Traceback: %s", traceback.format_exc())
    raise

# Log that the module was loaded successfully
_LOGGER.debug("Smart Assist config_flow module loaded successfully")


async def fetch_model_providers(api_key: str, model_id: str) -> list[dict[str, str]]:
    """Fetch available providers for a specific model from OpenRouter API.
    
    Uses the /api/v1/models/:author/:slug/endpoints API to get providers.
    Returns list of {"value": provider_tag, "label": display_name} dicts.
    Always includes "auto" as first option.
    """
    # Always include auto option
    providers = [{"value": "auto", "label": "Automatic (Best Price)"}]
    
    # Parse model_id to get author/slug format
    if "/" not in model_id:
        _LOGGER.warning("Invalid model_id format: %s", model_id)
        return providers
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        # URL encode the model_id (author/slug format)
        url = f"https://openrouter.ai/api/v1/models/{model_id}/endpoints"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    _LOGGER.warning(
                        "Failed to fetch providers for model %s: %s", 
                        model_id, response.status
                    )
                    return providers
                
                data = await response.json()
                endpoints = data.get("data", {}).get("endpoints", [])
                
                if not endpoints:
                    _LOGGER.debug("No endpoints found for model %s", model_id)
                    return providers
                
                # Extract unique providers and sort by price
                seen_providers: set[str] = set()
                for endpoint in sorted(
                    endpoints, 
                    key=lambda e: float(e.get("pricing", {}).get("prompt", "999"))
                ):
                    tag = endpoint.get("tag", "")
                    provider_name = endpoint.get("provider_name", tag)
                    quantization = endpoint.get("quantization", "")
                    
                    # Skip if already seen this base provider
                    # Some providers have variants like deepinfra/fp4, deepinfra/turbo
                    base_provider = tag.split("/")[0] if "/" in tag else tag
                    
                    if tag and tag not in seen_providers:
                        seen_providers.add(tag)
                        # Add pricing info and quantization to label
                        pricing = endpoint.get("pricing", {})
                        prompt_price = pricing.get("prompt", "0")
                        try:
                            price_per_m = float(prompt_price) * 1_000_000
                            if quantization and quantization != "unknown":
                                label = f"{provider_name} ({quantization}) - ${price_per_m:.2f}/M"
                            else:
                                label = f"{provider_name} - ${price_per_m:.2f}/M"
                        except (ValueError, TypeError):
                            label = provider_name
                        
                        providers.append({"value": tag, "label": label})
                
                _LOGGER.debug(
                    "Fetched %d providers for model %s", 
                    len(providers) - 1, model_id
                )
                return providers
                
    except (aiohttp.ClientError, TimeoutError, Exception) as err:
        _LOGGER.warning("Error fetching providers for model %s: %s", model_id, err)
        return providers


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
        _LOGGER.info("Smart Assist: ConfigFlow.__init__ called")
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
        _LOGGER.info("Smart Assist: async_step_user called with input: %s", user_input is not None)
        errors: dict[str, str] = {}

        try:
            if user_input is not None:
                _LOGGER.info("Smart Assist: Validating API key...")
                # Validate API key
                if await validate_api_key(user_input[CONF_API_KEY]):
                    _LOGGER.info("Smart Assist: API key valid, proceeding to model step")
                    self._data.update(user_input)
                    return await self.async_step_model()
                _LOGGER.warning("Smart Assist: API key validation failed")
                errors["base"] = "invalid_api_key"

            _LOGGER.info("Smart Assist: Showing user form")
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
        except Exception as e:
            _LOGGER.exception("Smart Assist: Error in async_step_user: %s", e)
            raise

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle model selection step."""
        if user_input is not None:
            self._data.update(user_input)
            # Proceed to provider selection (dynamically based on model)
            return await self.async_step_provider()

        # Fetch models from OpenRouter (with fallback to static list)
        if self._available_models is None:
            api_key = self._data.get(CONF_API_KEY, "")
            self._available_models = await fetch_openrouter_models(api_key)
        
        model_options = self._available_models

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

    async def async_step_provider(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle provider selection step (dynamic based on selected model)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_behavior()

        # Fetch available providers for the selected model
        api_key = self._data.get(CONF_API_KEY, "")
        model_id = self._data.get(CONF_MODEL, DEFAULT_MODEL)
        
        provider_options = await fetch_model_providers(api_key, model_id)
        
        return self.async_show_form(
            step_id="provider",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROVIDER, default=DEFAULT_PROVIDER): SelectSelector(
                        SelectSelectorConfig(
                            options=provider_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            description_placeholders={
                "model": model_id,
                "provider_count": str(len(provider_options) - 1),  # -1 for "auto"
                "caching_docs_url": "https://openrouter.ai/docs/guides/best-practices/prompt-caching",
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
                                {"value": "auto", "label": "Auto-detect"},
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

    _available_models: list[dict[str, str]] | None = None
    _available_providers: list[dict[str, str]] | None = None
    _options_data: dict[str, Any]

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        # Merge data and options - options take precedence
        self._options_data = {**config_entry.data, **config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Model selection."""
        if user_input is not None:
            self._options_data.update(user_input)
            # Reset providers cache when model changes
            self._available_providers = None
            return await self.async_step_provider()

        # Merge data and options - options take precedence
        current = self._options_data
        api_key = current.get(CONF_API_KEY, "")
        
        if self._available_models is None:
            self._available_models = await fetch_openrouter_models(api_key)
        
        model_options = list(self._available_models)
        current_model = current.get(CONF_MODEL, DEFAULT_MODEL)
        model_ids = [m["value"] for m in model_options]
        if current_model not in model_ids:
            model_options.insert(0, {"value": current_model, "label": f"{current_model} (current)"})

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
                            custom_value=True,
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
                }
            ),
        )

    async def async_step_provider(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Provider selection."""
        if user_input is not None:
            self._options_data.update(user_input)
            return await self.async_step_behavior()

        current = self._options_data
        api_key = current.get(CONF_API_KEY, "")
        current_model = current.get(CONF_MODEL, DEFAULT_MODEL)
        
        # Fetch providers for the selected model
        if self._available_providers is None:
            self._available_providers = await fetch_model_providers(api_key, current_model)
        
        provider_options = list(self._available_providers)
        current_provider = current.get(CONF_PROVIDER, DEFAULT_PROVIDER)
        provider_ids = [p["value"] for p in provider_options]
        if current_provider not in provider_ids:
            provider_options.insert(0, {"value": current_provider, "label": f"{current_provider} (current)"})

        return self.async_show_form(
            step_id="provider",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PROVIDER, default=current_provider
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=provider_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            description_placeholders={
                "model": current_model,
            },
        )

    async def async_step_behavior(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: Behavior settings."""
        if user_input is not None:
            self._options_data.update(user_input)
            return await self.async_step_caching()

        current = self._options_data

        return self.async_show_form(
            step_id="behavior",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LANGUAGE,
                        default=current.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "auto", "label": "Auto-detect"},
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
                }
            ),
        )

    async def async_step_caching(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 4: Caching settings."""
        if user_input is not None:
            self._options_data.update(user_input)
            return await self.async_step_advanced()

        current = self._options_data

        return self.async_show_form(
            step_id="caching",
            data_schema=vol.Schema(
                {
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
                }
            ),
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 5: Advanced settings."""
        if user_input is not None:
            self._options_data.update(user_input)
            # Remove API key from options (it's in data)
            options_to_save = {k: v for k, v in self._options_data.items() if k != CONF_API_KEY}
            
            # Apply debug logging setting immediately
            debug_enabled = options_to_save.get(CONF_DEBUG_LOGGING, DEFAULT_DEBUG_LOGGING)
            self._apply_debug_logging(debug_enabled)
            
            return self.async_create_entry(title="", data=options_to_save)

        current = self._options_data

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
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
                    vol.Required(
                        CONF_DEBUG_LOGGING,
                        default=current.get(CONF_DEBUG_LOGGING, DEFAULT_DEBUG_LOGGING),
                    ): BooleanSelector(),
                }
            ),
        )

    def _apply_debug_logging(self, enabled: bool) -> None:
        """Apply debug logging setting to all Smart Assist loggers."""
        import logging
        level = logging.DEBUG if enabled else logging.INFO
        
        # Set level for all Smart Assist loggers
        loggers = [
            "custom_components.smart_assist",
            "custom_components.smart_assist.conversation",
            "custom_components.smart_assist.config_flow",
            "custom_components.smart_assist.llm.client",
            "custom_components.smart_assist.llm.tools",
            "custom_components.smart_assist.sensor",
        ]
        for logger_name in loggers:
            logging.getLogger(logger_name).setLevel(level)
        
        _LOGGER.info("Smart Assist debug logging %s", "enabled" if enabled else "disabled")
