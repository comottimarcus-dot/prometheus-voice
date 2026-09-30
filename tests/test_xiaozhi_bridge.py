from array import array
import unittest

from prometheus_voice.xiaozhi_bridge import X6_TOOLS, execute_x6_tool, mcp_envelope, pack_v2, parse_v2, resample_16_to_24, resample_24_to_16


class FakeX6Client:
    def snapshot(self):
        return {"route": "capabilities"}

    def information(self):
        return {"route": "information"}

    def sentinel(self):
        return {"route": "sentinel"}

    def sentinel_air(self):
        return {"route": "sentinel-air"}


class XiaoZhiBridgeTests(unittest.TestCase):
    def test_binary_protocol_v2_round_trip(self):
        self.assertEqual(parse_v2(pack_v2(b"opus", 60)), b"opus")


    def test_integer_rate_conversion_preserves_duration(self):
        samples = array("h", range(960))
        pcm16 = samples.tobytes()
        pcm24 = resample_16_to_24(pcm16)
        self.assertEqual(len(pcm24), 1440 * 2)
        self.assertEqual(len(resample_24_to_16(pcm24)), len(pcm16))

    def test_x6_tools_are_fixed_read_only_queries(self):
        client = FakeX6Client()
        self.assertEqual(execute_x6_tool(client, "get_shadowbroker_news", {}), {"route": "information"})
        self.assertEqual(execute_x6_tool(client, "get_sentinel_weather", {}), {"route": "sentinel"})
        self.assertEqual(execute_x6_tool(client, "get_sentinel_aircraft", {}), {"route": "sentinel-air"})
        self.assertEqual(execute_x6_tool(client, "get_x6_capabilities", {}), {"route": "capabilities"})
        self.assertEqual({tool["name"] for tool in X6_TOOLS if tool["name"].startswith("get_")}, {"get_x6_capabilities", "get_shadowbroker_news", "get_sentinel_weather", "get_sentinel_aircraft"})

    def test_x6_tools_reject_caller_arguments_and_unknown_operations(self):
        client = FakeX6Client()
        with self.assertRaises(ValueError):
            execute_x6_tool(client, "get_shadowbroker_news", {"route": "camera-capture"})
        with self.assertRaises(ValueError):
            execute_x6_tool(client, "camera", {})

    def test_camera_proxy_accepts_only_mcp_envelopes(self):
        self.assertTrue(mcp_envelope('{"type":"mcp","payload":{"jsonrpc":"2.0"}}'))
        self.assertFalse(mcp_envelope('{"type":"listen"}'))
        self.assertFalse(mcp_envelope('{"type":"mcp","payload":[]}'))
        self.assertFalse(mcp_envelope('not json'))
