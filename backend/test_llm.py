import asyncio
import json
import time
from unittest.mock import patch, MagicMock, AsyncMock
from llm_client import GeminiLLMClient, _CACHE, OPENROUTER_MODEL

async def test_llm_resiliency_cache():
    print("\n--- Testing LLM Caching and Deduplication ---")
    _CACHE.clear()
    client = GeminiLLMClient(native_key="dummy_native", openrouter_key="dummy_or")
    
    # 1. Setup a dummy response for requests.post
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "MOCKED_RESPONSE"}]}}]
    }
    
    with patch("requests.post", return_value=mock_resp) as mock_post:
        # Call it once
        r1, tag1 = await client._call_gemini([{"role": "user", "content": "hello"}])
        assert r1 == "MOCKED_RESPONSE"
        assert tag1 == "gemini_native"
        assert mock_post.call_count == 1
        
        # Call identical prompt again
        r2, tag2 = await client._call_gemini([{"role": "user", "content": "hello"}])
        assert r2 == "MOCKED_RESPONSE"
        assert tag2 == "gemini_native_cached"
        assert mock_post.call_count == 1, "Cache failed! API was called twice for identical prompt."
        print("[PASS] Caching working correctly.")

async def test_llm_resiliency_429():
    print("\n--- Testing LLM 429 Exponential Backoff ---")
    _CACHE.clear()
    
    client = GeminiLLMClient(native_key="dummy_native", openrouter_key="dummy_or")
    
    # Return 429 (Too Many Requests) twice, then 200
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.text = "Quota Exceeded"
    resp_429.json.side_effect = Exception("No JSON")
    
    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "RECOVERED"}]}}]
    }
    
    # Override sleep to run tests instantly
    with patch("requests.post", side_effect=[resp_429, resp_429, resp_200]) as mock_post:
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            r, tag = await client._call_gemini([{"role": "user", "content": "timeout_test"}])
            
            assert mock_post.call_count == 3
            assert mock_sleep.call_count >= 2
            
            # The backoffs were 1s, 2s. We assert sum of backoff values applied (excluding the native 6s throttle which might be called)
            # Actually, `asyncio.sleep` gets called with `6.0 - elapsed` (throttle lock), then `retry_delay_sec`
            # For 429, it sleeps delay which is 1, then 2.
            sleep_args = [args[0] for args, kwargs in mock_sleep.call_args_list]
            # Assure the delays reflect backoff (1s, 2s) were in the arguments!
            assert 1 in sleep_args, "Missing 1s exponential backoff"
            assert 2 in sleep_args, "Missing 2s exponential backoff"
            assert r == "RECOVERED"
            print("[PASS] Exponential Backoff on 429 verified natively.")

async def test_llm_resiliency_500():
    print("\n--- Testing LLM 500 Unrecoverable Fault ---")
    _CACHE.clear()
    
    client = GeminiLLMClient(native_key="dummy_native", openrouter_key="dummy_or")
    
    # Return 500 (Internal Server Error)
    resp_500 = MagicMock()
    resp_500.status_code = 500
    resp_500.text = "Internal Server Error"
    
    resp_or = MagicMock()
    resp_or.status_code = 200
    resp_or.json.return_value = {"choices": [{"message": {"content": "OPENROUTER_FALLBACK"}}]}
    
    with patch("requests.post", side_effect=[resp_500, resp_or]) as mock_post:
        r, tag = await client._call_gemini([{"role": "user", "content": "crash_test"}])
        assert mock_post.call_count == 2
        assert tag == "openrouter"
        assert r == "OPENROUTER_FALLBACK"
        print("[PASS] Fallback router cascade on unrecoverable 500 verified natively.")

async def main():
    await test_llm_resiliency_cache()
    await test_llm_resiliency_429()
    await test_llm_resiliency_500()

if __name__ == "__main__":
    asyncio.run(main())
