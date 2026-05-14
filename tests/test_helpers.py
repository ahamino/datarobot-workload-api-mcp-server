"""Tests for the WAPI helpers module."""

from wapi_mcp.helpers import (
    format_created_at,
    extract_bundle,
    extract_scaling_info,
    format_scaling_info,
    format_status_details,
)


class TestFormatCreatedAt:
    """Tests for format_created_at function."""

    def test_iso_format_with_z(self):
        """Test ISO format timestamp ending with Z."""
        result = format_created_at("2024-01-15T10:30:00Z")
        assert result == "2024-01-15 10:30:00"

    def test_iso_format_with_timezone(self):
        """Test ISO format timestamp with timezone offset."""
        result = format_created_at("2024-01-15T10:30:00+00:00")
        assert result == "2024-01-15 10:30:00"

    def test_iso_format_with_microseconds(self):
        """Test ISO format timestamp with microseconds."""
        result = format_created_at("2024-01-15T10:30:00.123456Z")
        assert "2024-01-15" in result
        assert "10:30:00" in result

    def test_empty_string(self):
        """Test empty string input."""
        result = format_created_at("")
        assert result == ""

    def test_none_like_empty(self):
        """Test None-like empty input."""
        result = format_created_at("")
        assert result == ""


class TestExtractBundle:
    """Tests for extract_bundle function."""

    def test_with_bundle_id(self):
        """Test extraction with resourceBundleId."""
        runtime = {
            "resources": [
                {"resourceBundleId": "gpu.t4.small"}
            ]
        }
        result = extract_bundle(runtime)
        assert result == "gpu.t4.small"

    def test_with_bundle_id_and_gpu_label(self):
        """Test extraction with both bundleId and gpuTypeLabel."""
        runtime = {
            "resources": [
                {"resourceBundleId": "gpu.t4.small", "gpuTypeLabel": "NVIDIA T4"}
            ]
        }
        result = extract_bundle(runtime)
        assert "gpu.t4.small" in result
        assert "NVIDIA T4" in result

    def test_empty_runtime(self):
        """Test with empty runtime."""
        result = extract_bundle({})
        assert result == ""

    def test_none_runtime(self):
        """Test with None runtime."""
        result = extract_bundle(None)
        assert result == ""

    def test_empty_resources(self):
        """Test with empty resources list."""
        runtime = {"resources": []}
        result = extract_bundle(runtime)
        assert result == ""


class TestExtractScalingInfo:
    """Tests for extract_scaling_info function."""

    def test_fixed_replicas(self):
        """Test extraction with fixed replica count."""
        runtime = {"replicaCount": 3}
        result = extract_scaling_info(runtime)
        assert result["replica_count"] == 3
        assert result["autoscaling_enabled"] is False

    def test_autoscaling_enabled(self):
        """Test extraction with autoscaling enabled."""
        runtime = {
            "replicaCount": 1,
            "autoscaling": {
                "enabled": True,
                "policies": [{
                    "minCount": 1,
                    "maxCount": 5,
                    "scalingMetric": "cpuAverageUtilization",
                    "target": 70
                }]
            }
        }
        result = extract_scaling_info(runtime)
        assert result["autoscaling_enabled"] is True
        assert result["min_replicas"] == 1
        assert result["max_replicas"] == 5
        assert result["scaling_metric"] == "cpuAverageUtilization"
        assert result["target"] == 70

    def test_none_runtime(self):
        """Test with None runtime."""
        result = extract_scaling_info(None)
        assert result["replica_count"] == 1
        assert result["autoscaling_enabled"] is False


class TestFormatScalingInfo:
    """Tests for format_scaling_info function."""

    def test_fixed_replicas(self):
        """Test formatting fixed replicas."""
        runtime = {"replicaCount": 2}
        result = format_scaling_info(runtime)
        assert "Replicas: 2" in result
        assert "fixed" in result

    def test_autoscaling_cpu(self):
        """Test formatting autoscaling with CPU metric."""
        runtime = {
            "autoscaling": {
                "enabled": True,
                "policies": [{
                    "minCount": 1,
                    "maxCount": 10,
                    "scalingMetric": "cpuAverageUtilization",
                    "target": 80
                }]
            }
        }
        result = format_scaling_info(runtime)
        assert "Autoscaling: enabled" in result
        assert "1-10" in result
        assert "80%" in result


class TestFormatStatusDetails:
    """Tests for format_status_details function."""

    def test_with_conditions(self):
        """Test formatting with conditions."""
        entity = {
            "statusDetails": {
                "conditions": [
                    {"name": "Ready", "value": "True"},
                    {"name": "ContainersReady", "value": "True"}
                ]
            }
        }
        result = format_status_details(entity)
        assert "Conditions:" in result
        assert "Ready=True" in result

    def test_with_log_tail(self):
        """Test formatting with log tail."""
        entity = {
            "statusDetails": {
                "logTail": ["Starting server...", "Listening on port 8080"]
            }
        }
        result = format_status_details(entity)
        assert "Recent logs:" in result
        assert "Starting server..." in result

    def test_empty_status_details(self):
        """Test with empty status details."""
        entity = {"statusDetails": {}}
        result = format_status_details(entity)
        assert "No status details available" in result

    def test_no_status_details(self):
        """Test with no status details key."""
        entity = {}
        result = format_status_details(entity)
        assert "No status details available" in result
