"""
OCI serves Gemini with apiFormat GENERIC, but only the last SYSTEM message of the
request reaches the model: earlier ones are silently ignored. With an agent prompt
followed by a later system message (a conversation summary, for example), the
agent prompt is dropped. For Gemini, every system message is merged into a single
SYSTEM message at the top, as the Vertex AI Gemini path already does with
``systemInstruction``.
"""

from litellm.llms.oci.chat.transformation import OCIChatConfig

COMPARTMENT_ID = "ocid1.compartment.oc1..xxxxxx"


def _oci_messages(model: str, messages: list) -> list:
    request = OCIChatConfig().transform_request(
        model=model,
        messages=messages,  # type: ignore
        optional_params={"oci_compartment_id": COMPARTMENT_ID},
        litellm_params={},
        headers={},
    )
    return request["chatRequest"]["messages"]


def _texts(message: dict) -> str:
    return "".join(part["text"] for part in message["content"])


CONVERSATION = [
    {"role": "system", "content": "Agent prompt"},
    {"role": "user", "content": "Hi"},
    {"role": "assistant", "content": "Hello"},
    {"role": "system", "content": "Conversation summary"},
    {"role": "user", "content": "And now?"},
]


class TestGeminiSystemMessages:
    def test_merges_every_system_message_into_one_at_the_top(self):
        messages = _oci_messages("google.gemini-2.5-flash", CONVERSATION)

        assert [m["role"] for m in messages] == ["SYSTEM", "USER", "ASSISTANT", "USER"]
        assert _texts(messages[0]) == "Agent prompt\n\nConversation summary"
        assert [_texts(m) for m in messages[1:]] == ["Hi", "Hello", "And now?"]

    def test_model_with_oci_prefix_is_also_merged(self):
        messages = _oci_messages("oci/google.gemini-2.5-pro", CONVERSATION)

        assert [m["role"] for m in messages].count("SYSTEM") == 1

    def test_content_parts_are_joined_and_empty_system_messages_dropped(self):
        messages = _oci_messages(
            "google.gemini-2.5-flash",
            [
                {"role": "system", "content": [{"type": "text", "text": "Part A\n"}, {"type": "text", "text": "Part B"}]},
                {"role": "system", "content": "  "},
                {"role": "user", "content": "Hi"},
                {"role": "system", "content": "Late rule"},
            ],
        )

        assert [m["role"] for m in messages] == ["SYSTEM", "USER"]
        assert _texts(messages[0]) == "Part A\nPart B\n\nLate rule"

    def test_single_leading_system_message_passes_unchanged(self):
        messages = _oci_messages(
            "google.gemini-2.5-flash",
            [{"role": "system", "content": "Agent prompt"}, {"role": "user", "content": "Hi"}],
        )

        assert [m["role"] for m in messages] == ["SYSTEM", "USER"]
        assert _texts(messages[0]) == "Agent prompt"

    def test_does_not_mutate_the_caller_messages(self):
        messages = [dict(m) for m in CONVERSATION]
        _oci_messages("google.gemini-2.5-flash", messages)

        assert messages == CONVERSATION


class TestOtherGenericModelsKeepSystemPositions:
    def test_grok_keeps_each_system_message_in_place(self):
        messages = _oci_messages("xai.grok-4", CONVERSATION)

        assert [m["role"] for m in messages] == ["SYSTEM", "USER", "ASSISTANT", "SYSTEM", "USER"]
