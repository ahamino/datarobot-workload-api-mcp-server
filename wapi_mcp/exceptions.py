"""
Custom exceptions for the WAPI MCP Server.
"""

import json


class WapiConfigError(Exception):
    """Raised when required configuration is missing."""
    pass


class WapiAPIError(Exception):
    """Raised when an API request fails with detailed error information."""

    def __init__(self, status_code: int, method: str, url: str, response_body: str):
        self.status_code = status_code
        self.method = method
        self.url = url
        self.response_body = response_body
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format a helpful error message based on the status code."""
        base_msg = f"API Error {self.status_code}: {self.method} {self.url}"

        # Parse response body for details
        detail = self.response_body
        validation_errors = []

        try:
            body = json.loads(self.response_body)
            if isinstance(body, dict):
                # Handle Pydantic/FastAPI validation errors (common in 422 responses)
                if "detail" in body and isinstance(body["detail"], list):
                    for err in body["detail"]:
                        if isinstance(err, dict):
                            loc = " -> ".join(str(x) for x in err.get("loc", [])) or "(root)"
                            msg = err.get("msg", "") or err.get("message", "")
                            err_type = err.get("type", "")
                            # Build error line with available info
                            if msg:
                                err_line = f"  - {loc}: {msg}"
                                if err_type:
                                    err_line += f" (type: {err_type})"
                            elif err_type:
                                err_line = f"  - {loc}: validation error (type: {err_type})"
                            else:
                                # Fallback: show raw error dict
                                err_line = f"  - {json.dumps(err)}"
                            validation_errors.append(err_line)
                        elif isinstance(err, str):
                            validation_errors.append(f"  - {err}")
                    if validation_errors:
                        detail = "Validation errors:\n" + "\n".join(validation_errors)
                    else:
                        # Empty list or couldn't parse - show raw
                        detail = f"Validation error: {json.dumps(body['detail'])}"
                elif "detail" in body and isinstance(body["detail"], str):
                    detail = body["detail"]
                elif "message" in body:
                    detail = body["message"]
                elif "error" in body:
                    detail = body["error"] if isinstance(body["error"], str) else json.dumps(body["error"])
                else:
                    # Show full response for unknown formats
                    detail = json.dumps(body, indent=2)
        except json.JSONDecodeError:
            # Not JSON, use raw response
            pass
        except Exception as e:
            # Parsing failed, show raw response with note
            detail = f"{self.response_body}\n(Error parsing response: {e})"

        # Provide helpful guidance based on status code
        guidance = self._get_guidance()

        return f"{base_msg}\n\nServer response: {detail}{guidance}"

    def _get_guidance(self) -> str:
        """Append a short, accurate hint based on HTTP status code.

        The server's own validation detail (parsed in _format_message) is the
        source of truth. Keep these hints generic and one line — do NOT restate
        request schemas here, which drift from the API and mislead callers. For
        the exact accepted shape, query the spec via read_openapi_spec().
        """
        hints = {
            400: "Bad request — malformed payload or invalid field values. See the server response above.",
            401: "Unauthorized — check that DATAROBOT_API_TOKEN is valid and not expired.",
            403: "Forbidden — your user lacks permission for this resource.",
            404: "Not found — check the ID is correct and the resource still exists.",
            409: "Conflict — the resource is in a state that blocks this action (e.g. stop a running workload before deleting).",
            422: "Validation failed — see the server response above for the exact field(s). "
                 "Use read_openapi_spec(schema_name=...) for the accepted shape. "
                 "If this is `runtime_image_uri ... None` on workload create, the artifact's "
                 "build is likely still BUILT (built but not pushed) rather than COMPLETED — wait "
                 "for COMPLETED, then retry.",
            500: "Internal server error — usually transient; retry shortly.",
        }
        if self.status_code in (502, 503, 504):
            return "\n\nService unavailable/timeout — wait a moment and retry."
        hint = hints.get(self.status_code)
        return f"\n\n{hint}" if hint else ""
