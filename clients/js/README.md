# lemory-client (TypeScript)

Zero-dependency client for the [Lemory](../../README.md) REST API — use your
Markdown vault as memory from Node/Bun/Deno agents (Vercel AI SDK,
LangChain.js, plain scripts).

```ts
import { Lemory } from "lemory-client";

const mem = new Lemory({ client: "my-agent" });          // shows up in the dashboard
const hits = await mem.search("결제 어떻게 하기로 했지?");    // hybrid
const instant = await mem.search("결제", { mode: "fast" }); // no-embedding, ~ms
await mem.remember("환불은 비동기 큐로 결정", { title: "환불 결정" });
```

Remote (phone/tailnet): run `lemory serve --host 0.0.0.0` with `api_token`
set in `lemory.toml`, then `new Lemory({ baseUrl, token })`.

Not yet on npm — build locally: `npm run build` (needs only `typescript`).
