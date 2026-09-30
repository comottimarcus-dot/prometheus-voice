import unittest
from prometheus_voice.x6_client import validate_sentinel_air


def payload():
    return dict(type='x6_sentinel_air_result',request_id='q',status='ok',schema_version=1,
                node='sentinel-nm0',source='adsb.fi',scope='filtered_display_targets',targets=7,
                range_nm=25,display_limit=40,limit_reached=False,fetch_age_seconds=1,
                source_updated_at=None,execution_authorized=False,node_identity_verified=False,
                source_transport_verified=False)


class SentinelAirTests(unittest.TestCase):
    def test_projects_count_without_private_data(self):
        result=validate_sentinel_air({**payload(),'private':'hidden'},'q')
        self.assertEqual(result['targets'],7)
        self.assertNotIn('private',result)

    def test_invalid_age_count_and_identity_fail_closed(self):
        for change in ({'targets':True},{'targets':41},{'fetch_age_seconds':46},
                       {'source':'other'},{'range_nm':True},{'limit_reached':True},
                       {'node_identity_verified':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_sentinel_air({**payload(),**change},'q')
