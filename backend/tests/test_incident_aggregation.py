import unittest

from app.services.incident_aggregation import can_merge_locations, haversine_m


class IncidentAggregationTests(unittest.TestCase):
    def setUp(self):
        self.first = {
            "latitude": 29.6857,
            "longitude": 76.9905,
            "accuracy_m": 5.0,
            "location_source": "synthetic",
            "is_simulated": 1,
        }

    def test_haversine_zero_distance(self):
        self.assertAlmostEqual(
            haversine_m(29.6857, 76.9905, 29.6857, 76.9905), 0.0
        )

    def test_same_source_nearby_accurate_points_can_merge(self):
        second = dict(self.first, latitude=29.68571, longitude=76.99051)
        self.assertTrue(can_merge_locations(self.first, second))

    def test_simulated_and_real_points_never_merge(self):
        second = dict(self.first, is_simulated=0)
        self.assertFalse(can_merge_locations(self.first, second))

    def test_unknown_or_poor_accuracy_never_auto_merges(self):
        second = dict(self.first, accuracy_m=None)
        self.assertFalse(can_merge_locations(self.first, second))
        third = dict(self.first, accuracy_m=50.0)
        self.assertFalse(can_merge_locations(self.first, third))

    def test_distant_points_do_not_merge(self):
        second = dict(self.first, latitude=29.6865, longitude=76.9912)
        self.assertFalse(can_merge_locations(self.first, second))


if __name__ == "__main__":
    unittest.main()
