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
    from homeassistant.config_entries import (
        ConfigEntry,
        ConfigFlow,
        ConfigFlowResult,
        ConfigSubentryFlow,
        OptionsFlow,
        SubentryFlowResult,
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
        CONF_TASK_ENABLE_CACHE_WARMING,
        CONF_TASK_ENABLE_PROMPT_CACHING,
        CONF_TASK_SYSTEM_PROMPT,
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
        DEFAULT_TASK_ENABLE_CACHE_WARMING,
        DEFAULT_TASK_ENABLE_PROMPT_CACHING,
        DEFAULT_TASK_SYSTEM_PROMPT,
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
    
    Model variants like :free or :exacto are kept as-is since they have
    different provider availability.
    """
    _LOGGER.debug("fetch_model_providers: Starting for model %s", model_id)
    
    # Always include auto option
    providers = [{"value": "auto", "label": "Automatic (Best Price)"}]
    
    # Parse model_id to get author/slug format
    if "/" not in model_id:
        _LOGGER.warning("fetch_model_providers: Invalid model_id format: %s", model_id)
        return providers
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        url = f"https://openrouter.ai/api/v1/models/{model_id}/endpoints"
        _LOGGER.debug("fetch_model_providers: Fetching from %s", url)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                _LOGGER.debug("fetch_model_providers: Response status %s", response.status)
                if response.status != 200:
                    _LOGGER.warning(
                        "fetch_model_providers: Failed to fetch for model %s: status %s", 
                        model_id, response.status
                    )
                    return providers
                
                data = await response.json()
                endpoints = data.get("data", {}).get("endpoints", [])
                _LOGGER.debug("fetch_model_providers: Found %d endpoints for %s", len(endpoints), model_id)
                
                if not endpoints:
                    _LOGGER.debug("fetch_model_providers: No endpoints found for model %s", model_id)
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
                
                _LOGGER.info(
                    "fetch_model_providers: Fetched %d providers for model %s", 
                    len(providers) - 1, model_id
                )
                return providers
                
    except (aiohttp.ClientError, TimeoutError, Exception) as err:
        _LOGGER.warning("fetch_model_providers: Error for model %s: %s", model_id, err)
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
    """Handle a config flow for Smart Assist.
    
    This handles initial API key setup. After setup, users can add
    Conversation Agents and AI Tasks via subentries.
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
        """Handle the API configuration step."""
        _LOGGER.info("Smart Assist: async_step_user called with input: %s", user_input is not None)
        errors: dict[str, str] = {}

        try:
            if user_input is not None:
                _LOGGER.info("Smart Assist: Validating API key...")
                # Validate API key
                if await validate_api_key(user_input[CONF_API_KEY]):
                    _LOGGER.info("Smart Assist: API key valid, creating entry")
                    self._data.update(user_input)
                    
                    # Create the config entry with just the API key
                    return self.async_create_entry(
                        title="Smart Assist",
                        data=self._data,
                    )
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


# =============================================================================
# SUBENTRY FLOW HANDLERS
# =============================================================================

class SmartAssistSubentryFlowHandler(ConfigSubentryFlow):
    """Base class for Smart Assist subentry flows."""
    
    def _get_api_key(self) -> str:
        """Get API key from parent config entry."""
        return self._get_entry().data.get(CONF_API_KEY, "")
    
    async def _fetch_models(self) -> list[dict[str, str]]:
        """Fetch available models from OpenRouter."""
        return await fetch_openrouter_models(self._get_api_key())
    
    async def _fetch_providers(self, model_id: str) -> list[dict[str, str]]:
        """Fetch available providers for a model."""
        return await fetch_model_providers(self._get_api_key(), model_id)


class ConversationFlowHandler(SmartAssistSubentryFlowHandler):
    """Handle subentry flow for Conversation Agents.
    
    Flow steps:
    1. user: Model selection only (so we can fetch providers in next step)
    2. settings: Provider + temperature + max_tokens + all behavior settings
    3. prompt: System prompt customization
    
    Two-step approach allows dynamic provider loading after model is selected.
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
        """Handle first step - model selection only."""
        if user_input is not None:
            self._data.update(user_input)
            # Now go to settings step where we can fetch providers for the selected model
            return await self.async_step_settings()
        
        # Fetch models
        if self._available_models is None:
            self._available_models = await self._fetch_models()
        
        return self.async_show_form(
            step_id="user",
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
            return await self.async_step_prompt()
        
        # Fetch providers for the selected model (now we know the model!)
        model_id = self._data.get(CONF_MODEL, DEFAULT_MODEL)
        if self._available_providers is None:
            self._available_providers = await self._fetch_providers(model_id)
        
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROVIDER, default=DEFAULT_PROVIDER): SelectSelector(
                        SelectSelectorConfig(
                            options=self._available_providers,
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
        """Handle reconfiguration step 1 - model selection."""
        # Pre-fill with existing values on first call
        if not self._data:
            self._data = dict(self._get_reconfigure_subentry().data)
        
        if user_input is not None:
            self._data[CONF_MODEL] = user_input[CONF_MODEL]
            # Reset providers so they get refetched for new model
            self._available_providers = None
            return await self.async_step_reconfigure_settings()
        
        # Fetch models for dropdown
        if self._available_models is None:
            self._available_models = await self._fetch_models()
        
        # Ensure current model is in the list
        model_options = list(self._available_models)
        current_model = self._data.get(CONF_MODEL, DEFAULT_MODEL)
        model_ids = [m["value"] for m in model_options]
        if current_model not in model_ids:
            model_options.insert(0, {"value": current_model, "label": f"{current_model} (current)"})
        
        return self.async_show_form(
            step_id="reconfigure",
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
        """Handle reconfiguration step 2 - provider and all settings."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=self._data,
            )
        
        # Fetch providers for the selected model
        model_id = self._data.get(CONF_MODEL, DEFAULT_MODEL)
        if self._available_providers is None:
            self._available_providers = await self._fetch_providers(model_id)
        
        # Ensure current provider is in the list
        provider_options = list(self._available_providers)
        current_provider = self._data.get(CONF_PROVIDER, DEFAULT_PROVIDER)
        provider_values = [p["value"] for p in provider_options]
        if current_provider not in provider_values:
            provider_options.insert(0, {"value": current_provider, "label": f"{current_provider} (current)"})
        
        return self.async_show_form(
            step_id="reconfigure_settings",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_PROVIDER): SelectSelector(
                            SelectSelectorConfig(
                                options=provider_options,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Required(CONF_TEMPERATURE): NumberSelector(
                            NumberSelectorConfig(
                                min=0.0, max=1.0, step=0.1, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                        vol.Required(CONF_MAX_TOKENS): NumberSelector(
                            NumberSelectorConfig(
                                min=100, max=4000, step=100, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                        vol.Required(CONF_LANGUAGE): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    {"value": "auto", "label": "Auto-detect"},
                                    {"value": "en", "label": "English"},
                                    {"value": "de", "label": "Deutsch"},
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Required(CONF_EXPOSED_ONLY): BooleanSelector(),
                        vol.Required(CONF_CONFIRM_CRITICAL): BooleanSelector(),
                        vol.Required(CONF_MAX_HISTORY): NumberSelector(
                            NumberSelectorConfig(min=1, max=20, step=1, mode=NumberSelectorMode.SLIDER)
                        ),
                        vol.Required(CONF_ENABLE_WEB_SEARCH): BooleanSelector(),
                        vol.Required(CONF_ENABLE_PROMPT_CACHING): BooleanSelector(),
                        vol.Required(CONF_CACHE_TTL_EXTENDED): BooleanSelector(),
                        vol.Required(CONF_ENABLE_CACHE_WARMING): BooleanSelector(),
                        vol.Required(CONF_CACHE_REFRESH_INTERVAL): NumberSelector(
                            NumberSelectorConfig(min=1, max=55, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX)
                        ),
                        vol.Required(CONF_CLEAN_RESPONSES): BooleanSelector(),
                        vol.Required(CONF_ASK_FOLLOWUP): BooleanSelector(),
                        vol.Required(CONF_USER_SYSTEM_PROMPT): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
                        ),
                    }
                ),
                self._data,
            ),
        )


class AITaskFlowHandler(SmartAssistSubentryFlowHandler):
    """Handle subentry flow for AI Tasks.
    
    Flow steps:
    1. user: Model selection only (so we can fetch providers in next step)
    2. settings: Provider + temperature + all other settings
    
    Two-step approach allows dynamic provider loading after model is selected.
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
        """Handle first step - model selection only."""
        if user_input is not None:
            self._data.update(user_input)
            # Now go to settings step where we can fetch providers for the selected model
            return await self.async_step_settings()
        
        # Fetch models
        if self._available_models is None:
            self._available_models = await self._fetch_models()
        
        return self.async_show_form(
            step_id="user",
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
        
        # Fetch providers for the selected model (now we know the model!)
        model_id = self._data.get(CONF_MODEL, DEFAULT_MODEL)
        if self._available_providers is None:
            self._available_providers = await self._fetch_providers(model_id)
        
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROVIDER, default=DEFAULT_PROVIDER): SelectSelector(
                        SelectSelectorConfig(
                            options=self._available_providers,
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
                    vol.Required(
                        CONF_TASK_SYSTEM_PROMPT, default=DEFAULT_TASK_SYSTEM_PROMPT
                    ): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                            multiline=True,
                        )
                    ),
                    vol.Required(
                        CONF_TASK_ENABLE_PROMPT_CACHING, default=DEFAULT_TASK_ENABLE_PROMPT_CACHING
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_TASK_ENABLE_CACHE_WARMING, default=DEFAULT_TASK_ENABLE_CACHE_WARMING
                    ): BooleanSelector(),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration step 1 - model selection."""
        # Pre-fill with existing values on first call
        if not self._data:
            self._data = dict(self._get_reconfigure_subentry().data)
        
        if user_input is not None:
            self._data[CONF_MODEL] = user_input[CONF_MODEL]
            # Reset providers so they get refetched for new model
            self._available_providers = None
            return await self.async_step_reconfigure_settings()
        
        # Fetch models for dropdown
        if self._available_models is None:
            self._available_models = await self._fetch_models()
        
        # Ensure current model is in the list
        model_options = list(self._available_models)
        current_model = self._data.get(CONF_MODEL, DEFAULT_MODEL)
        model_ids = [m["value"] for m in model_options]
        if current_model not in model_ids:
            model_options.insert(0, {"value": current_model, "label": f"{current_model} (current)"})
        
        return self.async_show_form(
            step_id="reconfigure",
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
        """Handle reconfiguration step 2 - provider and all settings."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=self._data,
            )
        
        # Fetch providers for the selected model
        model_id = self._data.get(CONF_MODEL, DEFAULT_MODEL)
        if self._available_providers is None:
            self._available_providers = await self._fetch_providers(model_id)
        
        # Ensure current provider is in the list
        provider_options = list(self._available_providers)
        current_provider = self._data.get(CONF_PROVIDER, DEFAULT_PROVIDER)
        provider_values = [p["value"] for p in provider_options]
        if current_provider not in provider_values:
            provider_options.insert(0, {"value": current_provider, "label": f"{current_provider} (current)"})
        
        return self.async_show_form(
            step_id="reconfigure_settings",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_PROVIDER): SelectSelector(
                            SelectSelectorConfig(
                                options=provider_options,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Required(CONF_TEMPERATURE): NumberSelector(
                            NumberSelectorConfig(
                                min=0.0, max=1.0, step=0.1, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                        vol.Required(CONF_MAX_TOKENS): NumberSelector(
                            NumberSelectorConfig(
                                min=100, max=4000, step=100, mode=NumberSelectorMode.SLIDER
                            )
                        ),
                        vol.Required(CONF_LANGUAGE): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    {"value": "auto", "label": "Auto-detect"},
                                    {"value": "en", "label": "English"},
                                    {"value": "de", "label": "Deutsch"},
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Required(CONF_EXPOSED_ONLY): BooleanSelector(),
                        vol.Required(CONF_TASK_SYSTEM_PROMPT): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)
                        ),
                        vol.Required(CONF_TASK_ENABLE_PROMPT_CACHING): BooleanSelector(),
                        vol.Required(CONF_TASK_ENABLE_CACHE_WARMING): BooleanSelector(),
                    }
                ),
                self._data,
            ),
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
            self._apply_debug_logging(debug_enabled)
            
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
