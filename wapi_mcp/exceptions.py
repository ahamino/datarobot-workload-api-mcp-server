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
        """Get helpful guidance based on HTTP status code."""
        if self.status_code == 400:
            return """

BAD REQUEST - The request was malformed.
Common causes:
- Invalid JSON syntax in payload
- Missing required fields
- Invalid field values or types"""

        elif self.status_code == 401:
            return """

UNAUTHORIZED - Authentication failed.
Check that DATAROBOT_API_TOKEN is valid and not expired."""

        elif self.status_code == 403:
            return """

FORBIDDEN - You don't have permission for this action.
Check your user permissions for this resource."""

        elif self.status_code == 404:
            return """

NOT FOUND - The resource doesn't exist.
Check that the ID is correct and the resource hasn't been deleted."""

        elif self.status_code == 409:
            return """

CONFLICT - Resource state conflict.
Common causes:
- Trying to delete a running workload (stop it first)
- Trying to update a registered artifact (create a new version instead)
- Resource name already exists"""

        elif self.status_code == 422:
            return """

UNPROCESSABLE ENTITY - Validation failed.

Common issues for WORKLOAD creation:
- 'type' must be 'generic' (literal value, not a variable)
- Port must be >= 1024 (non-privileged ports only)
- resourceRequest.cpu and resourceRequest.memory are REQUIRED
- Exactly ONE container must have 'primary: true'
- entrypoint must be array of strings: ["cmd", "arg1"]

Required CreateWorkloadRequest structure:
{
  "name": "workload-name",
  "artifactId": "existing-artifact-id"   // OR use inline 'artifact'
  // OR
  "artifact": {
    "name": "artifact-name",
    "type": "generic",                   // REQUIRED literal
    "spec": {
      "containerGroups": [{
        "containers": [{
          "imageUri": "registry/image:tag",
          "port": 8000,                   // Must be >= 1024
          "primary": true,                // Required on one container
          "resourceRequest": {
            "cpu": 1.0,                   // Required (number)
            "memory": 536870912           // Required (bytes)
          }
        }]
      }]
    }
  },
  "runtime": {"replicaCount": 1}
}

For ARTIFACT creation: type must be "generic" (the literal string)

For probes: 'path' is REQUIRED in ProbeConfig:
  "readinessProbe": {"path": "/healthz", "port": 8000}"""

        elif self.status_code == 500:
            return """

INTERNAL SERVER ERROR - Server-side error.
This is usually temporary. Try again in a few moments."""

        elif self.status_code in (502, 503, 504):
            return """

SERVICE UNAVAILABLE/TIMEOUT - The service is temporarily unavailable.
Wait a moment and retry the request."""

        return ""
