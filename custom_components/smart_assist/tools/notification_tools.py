"""Notification tools for Smart Assist.

Provides tools for sending content (links, messages, etc.) to devices
via Home Assistant's notification services.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant

from .base import BaseTool, ToolParameter, ToolResult

_LOGGER = logging.getLogger(__name__)

# URL regex pattern for detecting links in content
URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+'
)


class SendTool(BaseTool):
    """Tool for sending content to devices via notifications.
    
    This tool dynamically discovers available notification services and allows
    the LLM to send links, messages, or other content to them.
    
    Typical use cases:
    - Send search result links to user's device
    - Send reminders or messages
    - Forward information to specific notification targets
    """

    name = "send"
    description = "Send content (links, text, messages) to a device or notification service."
    parameters = [
        ToolParameter(
            name="content",
            type="string",
            description="The content to send (text message, URLs, or formatted message with links)",
            required=True,
        ),
        ToolParameter(
            name="target",
            type="string",
            description="Target device or notification service (from the available targets list in tool description)",
            required=True,
        ),
        ToolParameter(
            name="title",
            type="string",
            description="Title for the notification (optional, defaults to 'Smart Assist')",
            required=False,
        ),
    ]

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the send tool."""
        super().__init__(hass)
        self._cached_devices: list[str] | None = None
        self._logged_services = False
    
    def _get_mobile_app_services(self) -> list[str]:
        """Get all available mobile_app notification services.
        
        Returns list of device identifiers (without 'mobile_app_' prefix).
        Example: ['patrics_iphone', 'mamas_android', 'tablet']
        """
        notify_services = self._hass.services.async_services().get("notify", {})
        
        devices = []
        for service_name in notify_services:
            if service_name.startswith("mobile_app_"):
                # Extract device name: mobile_app_patrics_iphone -> patrics_iphone
                device_id = service_name.replace("mobile_app_", "", 1)
                devices.append(device_id)
        
        return sorted(devices)
    
    def _get_all_notify_services(self) -> list[str]:
        """Get all notification services (for groups, etc.).
        
        Returns full service names for non-mobile_app services.
        """
        notify_services = self._hass.services.async_services().get("notify", {})
        return [name for name in notify_services if not name.startswith("mobile_app_")]
    
    def _log_available_services(self) -> None:
        """Log available notification services (once per session)."""
        if self._logged_services:
            return
        
        mobile_devices = self._get_mobile_app_services()
        other_services = self._get_all_notify_services()
        
        _LOGGER.debug(
            "Send tool - available notification targets: mobile_apps=%s, other_services=%s",
            mobile_devices,
            other_services,
        )
        self._logged_services = True
    
    def get_schema(self) -> dict[str, Any]:
        """Get OpenAI-compatible tool schema with dynamic target list."""
        # Log available services (once)
        self._log_available_services()
        
        # Get available devices and services for the description
        devices = self._get_mobile_app_services()
        other_services = self._get_all_notify_services()
        all_targets = devices + other_services
        
        # Build dynamic description with available targets
        if all_targets:
            parts = []
            if devices:
                parts.append(f"Mobile devices: {', '.join(devices)}")
            if other_services and len(other_services) <= 5:
                parts.append(f"Other services: {', '.join(other_services)}")
            target_info = ". ".join(parts)
            description = (
                f"Send content (links, text, messages) to a notification target. "
                f"Available targets - {target_info}. "
                f"Use to send links, reminders, or messages to the user's device."
            )
        else:
            description = (
                "Send content via notification. No notification services found. "
                "Check if Home Assistant Companion App or other notify integrations are set up."
            )
        
        # Build schema with dynamic description
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            
            # Add target enum for better LLM selection (prefer mobile devices)
            if param.name == "target" and all_targets:
                prop["enum"] = all_targets
                prop["description"] = f"Target device or service. Available: {', '.join(all_targets)}"
            
            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def _extract_urls(self, content: str) -> list[str]:
        """Extract URLs from content string."""
        return URL_PATTERN.findall(content)
    
    def _find_matching_service(self, target: str) -> str | None:
        """Find the notification service matching the target.
        
        Args:
            target: User-provided target (e.g., 'patrics_iphone', 'patrics_handy')
            
        Returns:
            Full service name (e.g., 'mobile_app_patrics_iphone') or None
        """
        notify_services = self._hass.services.async_services().get("notify", {})
        
        # Normalize target for matching
        target_lower = target.lower().replace(" ", "_").replace("-", "_")
        
        # 1. Exact match for mobile_app_<target>
        mobile_app_service = f"mobile_app_{target_lower}"
        if mobile_app_service in notify_services:
            return mobile_app_service
        
        # 2. Exact match for standalone service (e.g., 'family', 'all_devices')
        if target_lower in notify_services:
            return target_lower
        
        # 3. Fuzzy match - find services containing the target
        for service_name in notify_services:
            service_lower = service_name.lower()
            # Check if target is contained in service name
            if target_lower in service_lower:
                return service_name
            # Check if main part matches (e.g., 'patrics' matches 'mobile_app_patrics_iphone')
            if service_lower.startswith("mobile_app_"):
                device_part = service_lower.replace("mobile_app_", "")
                if target_lower in device_part or device_part.startswith(target_lower):
                    return service_name
        
        return None

    async def execute(
        self,
        content: str,
        target: str,
        title: str = "Smart Assist",
    ) -> ToolResult:
        """Execute the send tool.
        
        Args:
            content: The content to send (text, URLs, etc.)
            target: Target device identifier
            title: Notification title
            
        Returns:
            ToolResult indicating success or failure
        """
        _LOGGER.debug("Send tool called: target='%s', title='%s', content_length=%d", target, title, len(content))
        
        # Find the matching notification service
        service_name = self._find_matching_service(target)
        _LOGGER.debug("Target '%s' resolved to service: %s", target, service_name)
        
        if not service_name:
            available = self._get_mobile_app_services()
            return ToolResult(
                success=False,
                message=f"Device '{target}' not found. Available devices: {', '.join(available) if available else 'none'}",
            )
        
        # Extract URLs from content for actionable notifications
        urls = self._extract_urls(content)
        
        # Build notification data
        notification_data: dict[str, Any] = {
            "title": title,
            "message": content,
        }
        
        # If content contains URLs, make them clickable
        if urls:
            # For single URL, make the notification itself clickable
            if len(urls) == 1:
                notification_data["data"] = {
                    "url": urls[0],
                    "clickAction": urls[0],  # Android
                }
            else:
                # For multiple URLs, create action buttons (max 3)
                actions = []
                for i, url in enumerate(urls[:3], 1):
                    # Create short label from URL
                    label = self._create_url_label(url, i)
                    actions.append({
                        "action": "URI",
                        "title": label,
                        "uri": url,
                    })
                
                notification_data["data"] = {
                    "actions": actions,
                    # Make first URL the main click action
                    "url": urls[0],
                    "clickAction": urls[0],
                }
        
        try:
            # Call the notification service
            await self._hass.services.async_call(
                "notify",
                service_name,
                notification_data,
                blocking=True,
            )
            
            # Build success message
            if urls:
                link_count = len(urls)
                link_text = "1 link" if link_count == 1 else f"{link_count} links"
                return ToolResult(
                    success=True,
                    message=f"Sent notification with {link_text} to {target}.",
                    data={"service": service_name, "urls": urls},
                )
            else:
                return ToolResult(
                    success=True,
                    message=f"Sent message to {target}.",
                    data={"service": service_name},
                )
                
        except Exception as err:
            _LOGGER.error("Failed to send notification: %s", err)
            return ToolResult(
                success=False,
                message=f"Failed to send notification: {err}",
            )
    
    def _create_url_label(self, url: str, index: int) -> str:
        """Create a short label for a URL action button.
        
        Args:
            url: The URL to create a label for
            index: The index number for fallback label
            
        Returns:
            Short label like 'example.com' or 'Link 1'
        """
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            # Use domain as label, e.g., 'en.wikipedia.org'
            domain = parsed.netloc
            # Remove 'www.' prefix
            if domain.startswith("www."):
                domain = domain[4:]
            # Truncate if too long
            if len(domain) > 20:
                domain = domain[:17] + "..."
            return domain
        except Exception:
            return f"Link {index}"
