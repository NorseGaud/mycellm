# Ollama SDK

mycellm is a drop-in replacement for Ollama. Any tool that uses the Ollama SDK or API works without code changes — just point it at mycellm's port.

## Configuration

Set the Ollama base URL to your mycellm node:

```bash
export OLLAMA_HOST=http://localhost:8420
```

Or configure per-tool (see examples below).

## Endpoints

mycellm implements the Ollama API at `/api`:

| Ollama endpoint | mycellm equivalent | Notes |
|----------------|-------------------|-------|
| `GET /api/tags` | Lists all models | Includes virtual `auto` model |
| `POST /api/show` | Model details | Works with `auto` and all loaded models |
| `POST /api/chat` | Chat completion | Translates to mycellm routing internally |

## OpenClaw

```json
{
  "models": {
    "providers": {
      "ollama": {
        "baseUrl": "http://localhost:8420"
      }
    },
    "profiles": {
      "assistant": {
        "provider": "ollama",
        "model": "auto"
      }
    }
  }
}
```

## Python (ollama-python)

```python
import ollama

client = ollama.Client(host="http://localhost:8420")

response = client.chat(
    model="auto",
    messages=[{"role": "user", "content": "Hello"}],
)
print(response["message"]["content"])
```

## JavaScript (ollama-js)

```javascript
import { Ollama } from "ollama";

const ollama = new Ollama({ host: "http://localhost:8420" });

const response = await ollama.chat({
  model: "auto",
  messages: [{ role: "user", content: "Hello" }],
});
console.log(response.message.content);
```

## How it works

mycellm translates Ollama API calls into its internal OpenAI-compatible
routing. The `auto` model lets mycellm pick the best available model
across all local, peer, and fleet nodes — so Ollama clients get
distributed inference without any special configuration.
