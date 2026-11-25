import json
import unittest

from capri_runtime.worker_protocol import (
    MAX_DEADLINE_MS,
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    WorkerProtocolError,
    WorkerRequest,
    WorkerResponse,
)


class WorkerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.request = WorkerRequest(
            "req-17", "math.factorial", {"number": 12}, 5_000
        )

    def test_request_round_trip_is_canonical(self):
        encoded = self.request.to_json()
        decoded = WorkerRequest.from_json(encoded)
        self.assertEqual(decoded, self.request)
        self.assertEqual(encoded, self.request.to_json())

    def test_response_round_trip_and_request_correlation(self):
        response = WorkerResponse(
            "req-17", "local-python-1", "succeeded", 4,
            output={"value": 479001600},
        )
        decoded = WorkerResponse.from_json(response.to_json())
        decoded.validate_for(self.request, expected_worker_id="local-python-1")
        self.assertEqual(decoded, response)

    def test_failed_response_requires_error_only(self):
        response = WorkerResponse(
            "req-17", "worker-1", "failed", 1, error="operation failed"
        )
        self.assertEqual(WorkerResponse.from_json(response.to_json()), response)
        with self.assertRaises(WorkerProtocolError):
            WorkerResponse("req-17", "worker-1", "failed", 1, output={}).to_json()

    def test_rejects_unknown_fields_and_protocol_versions(self):
        data = json.loads(self.request.to_json())
        data["permissions"] = ["admin"]
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest.from_json(json.dumps(data))
        data = json.loads(self.request.to_json())
        data["protocol_version"] = PROTOCOL_VERSION + 1
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest.from_json(json.dumps(data))

    def test_rejects_duplicate_keys_and_nonstandard_numbers(self):
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest.from_json(
                '{"protocol_version":1,"protocol_version":1}'
            )
        malformed = self.request.to_json().replace('"number":12', '"number":NaN')
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest.from_json(malformed)

    def test_rejects_invalid_identifiers_and_capabilities(self):
        for request_id in ("", "bad id", "x" * 129):
            with self.subTest(request_id=request_id):
                request = WorkerRequest(request_id, "math.factorial", {}, 100)
                with self.assertRaises(WorkerProtocolError):
                    request.to_json()
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest("req-1", "Math.Factorial", {}, 100).to_json()

    def test_deadline_is_bounded_and_exact_integer(self):
        for deadline in (0, -1, MAX_DEADLINE_MS + 1, True, 1.5):
            with self.subTest(deadline=deadline):
                with self.assertRaises(WorkerProtocolError):
                    WorkerRequest("req-1", "math.factorial", {}, deadline).to_json()

    def test_input_must_be_object_and_json_compatible(self):
        for payload in ([], "text", {"value": float("nan")}):
            with self.subTest(payload=payload):
                with self.assertRaises(WorkerProtocolError):
                    WorkerRequest("req-1", "math.factorial", payload, 100).to_json()

    def test_rejects_deeply_nested_payload(self):
        payload = {}
        cursor = payload
        for _ in range(34):
            cursor["next"] = {}
            cursor = cursor["next"]
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest("req-1", "math.factorial", payload, 100).to_json()

    def test_rejects_oversized_messages(self):
        payload = {"value": "x" * MAX_MESSAGE_BYTES}
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest("req-1", "math.factorial", payload, 100).to_json()
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest.from_json(" " * (MAX_MESSAGE_BYTES + 1))

    def test_response_cannot_be_replayed_for_another_request_or_worker(self):
        response = WorkerResponse(
            "req-18", "worker-1", "succeeded", 2, output={"value": 1}
        )
        with self.assertRaises(WorkerProtocolError):
            response.validate_for(self.request, expected_worker_id="worker-1")
        response = WorkerResponse(
            "req-17", "worker-2", "succeeded", 2, output={"value": 1}
        )
        with self.assertRaises(WorkerProtocolError):
            response.validate_for(self.request, expected_worker_id="worker-1")

    def test_rejects_boolean_protocol_version(self):
        data = json.loads(self.request.to_json())
        data["protocol_version"] = True
        with self.assertRaises(WorkerProtocolError):
            WorkerRequest.from_json(json.dumps(data))


    def test_validate_for_rejects_malformed_direct_instances(self):
        malformed_request = WorkerRequest("bad id", "math.factorial", {}, 100)
        response = WorkerResponse("bad id", "worker-1", "succeeded", 1, output={"value": 1})
        with self.assertRaises(WorkerProtocolError):
            response.validate_for(malformed_request, expected_worker_id="worker-1")

        valid_request = WorkerRequest("req-17", "math.factorial", {}, 100)
        malformed_response = WorkerResponse("req-17", "worker-1", "succeeded", True, output={"value": 1})
        with self.assertRaises(WorkerProtocolError):
            malformed_response.validate_for(valid_request, expected_worker_id="worker-1")

    def test_validate_for_rejects_reported_duration_over_deadline(self):
        short_request = WorkerRequest("req-17", "math.factorial", {}, 10)
        late_response = WorkerResponse("req-17", "worker-1", "succeeded", 11, output={"value": 1})
        with self.assertRaises(WorkerProtocolError):
            late_response.validate_for(short_request, expected_worker_id="worker-1")

    def test_worker_protocol_types_are_package_exports(self):
        from capri_runtime import WorkerProtocolError as ExportedError
        from capri_runtime import WorkerRequest as ExportedRequest
        from capri_runtime import WorkerResponse as ExportedResponse
        self.assertIs(ExportedError, WorkerProtocolError)
        self.assertIs(ExportedRequest, WorkerRequest)
        self.assertIs(ExportedResponse, WorkerResponse)


if __name__ == "__main__":
    unittest.main()
