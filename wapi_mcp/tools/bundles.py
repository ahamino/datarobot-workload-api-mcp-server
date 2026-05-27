"""Compute bundle listing.

Tools call ``server.get_client()`` so test patches of
``wapi_mcp_server.get_client`` take effect.
"""

import wapi_mcp_server as server


from wapi_mcp_server import mcp, traced_tool  # noqa: E402


@mcp.tool()
@traced_tool
async def bundle_list() -> str:
    """List available compute bundles - CALL THIS BEFORE creating workloads!

    Returns available CPU and GPU configurations. Use a single bundle ID with
    workload_create(resource_bundle_ids=["..."]). Choose EXACTLY ONE bundle —
    the parameter is a list for API compatibility but only one is allowed.

    GPU TYPE AND GPU VRAM ARE DETERMINED BY THE BUNDLE. There is no gpuType or
    gpuMemory field on a workload — selecting a resource bundle is the ONLY way
    to choose the GPU model (L4, A10G, H100, ...) and its VRAM. The `gpu`
    parameter on workload_create only sets the GPU count.

    Common bundles:
    - cpu.small, cpu.medium, cpu.large: CPU-only workloads
    - gpu.l4.small, gpu.a10g.medium: GPU workloads (check available types)
    """
    client = await server.get_client()
    result = await client.list_bundles()
    data = result.get("data", [])

    if not data:
        return "No compute bundles found."

    # Separate CPU and GPU bundles
    cpu_bundles = []
    gpu_bundles = []

    for b in data:
        bid = b.get("id", "")
        name = b.get("name", "")
        cpu_count = b.get("cpuCount", "")
        memory_bytes = b.get("memoryBytes", 0)
        memory_gb = f"{memory_bytes / (1024**3):.1f}GB" if memory_bytes else ""
        gpu_count = b.get("gpuCount", 0)
        gpu_type = b.get("gpuTypeLabel", "")

        if gpu_count and gpu_count > 0:
            gpu_info = f"{gpu_count}x {gpu_type}"
            gpu_bundles.append(f"  - {bid}: {name} | cpu={cpu_count} | mem={memory_gb} | gpu={gpu_info}")
        else:
            cpu_bundles.append(f"  - {bid}: {name} | cpu={cpu_count} | mem={memory_gb}")

    result_str = f"Found {len(data)} compute bundles:\n\n"

    if cpu_bundles:
        result_str += "CPU BUNDLES (for workload_create without gpu parameter):\n"
        result_str += "\n".join(cpu_bundles) + "\n\n"

    if gpu_bundles:
        result_str += "GPU BUNDLES (the bundle sets the GPU type AND VRAM):\n"
        result_str += "\n".join(gpu_bundles) + "\n\n"

    result_str += """USAGE:
  Option 1 - Use one bundle ID: workload_create(..., resource_bundle_ids=["cpu.small"])
             (pick EXACTLY ONE bundle — only a single bundle is allowed)
  Option 2 - CPU/memory only: workload_create(..., cpu=2, memory_bytes=4294967296)
  GPU type + VRAM: choose a GPU bundle above via resource_bundle_ids — they are
  NOT settable any other way (no gpuType/gpuMemory field)."""

    return result_str


__all__ = [
    "bundle_list",
]
