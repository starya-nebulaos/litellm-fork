# Upgrade do fork: 1.100.0 → 1.104.2 — análise de quebra

Escopo: o que **nós** usamos do LiteLLM (gateway `nebulaos-cloud/src/modules/ai-platform/_llm-gateway`, chart `nebulaos-infra/helm/dp-litellm-fork`). Branch `update-upstream-v1.104.2` = `litellm_internal_staging` (0f7b3cadc0) + merge da tag `v1.104.2`.

Legenda de evidência: **[código]** lido no fonte; **[teste]** executado localmente; **[inferido]** não executado.

## 1. Conclusão

- Nada do que usamos foi removido ou renomeado. Os endpoints, o header de custo, o formato de `tool_call_id` do Gemini, as chaves de config e o nosso bypass de preço continuam no lugar.
- O risco principal é operacional:
  - o merge vira deploy automático em prod;
  - 32 migrations rodam sozinhas no boot, no banco de prod.
- As migrations são todas aditivas, exceto uma renomeação de coluna numa tabela que não usamos. O rollback provavelmente funciona, mas isso é **[inferido]** e precisa de ensaio.
- A tabela de preços não muda o tier padrão dos modelos Gemini que usamos.

## 2. Como o deploy acontece

| Passo | Onde |
|---|---|
| Push em `litellm_internal_staging` dispara o build | `.github/workflows/build-ocir.yml:3-5` |
| Publica `litellm:<sha>` e `litellm:latest` no OCIR | `build-ocir.yml:40-42` |
| ArgoCD Image Updater segue `:latest` por digest e sincroniza sozinho | `nebulaos-infra/argocd/apps-dp-production/litellm-fork.yaml:10-12,27-30` |

Nenhum outro workflow publica imagem ou faz deploy em PR ou em push para outra branch. Conferido nos 53 workflows da branch e nos `pull_request_target` da base.

## 3. Migrations (`litellm-proxy-extras/.../migrations`)

Quando rodam: na subida do proxy (`prisma migrate deploy`, resolver v2, que agora é o default). Desligar exige `general_settings.disable_prisma_schema_update` ou a env `DISABLE_SCHEMA_UPDATE`; nenhum dos dois está setado no nosso chart. Quando há migration pendente, roda também uma checagem que aplica o diff entre o banco e o `schema.prisma`. Qualquer drift manual no banco será corrigido por ela.

| Grupo | Migrations | Tipo | Usamos? |
|---|---|---|---|
| Colunas novas com DEFAULT ou nullable em `Daily*Spend` (`gateway_injected_caching_savings_spend`, `timed_requests`, `total_response_time_ms`) | 20260824, 20260915_daily_response_time | aditiva | não lemos; o proxy escreve |
| `LiteLLM_SpendLogs.litellm_call_id TEXT` (nullable) | 20260831120000 | aditiva, instantânea (sem rewrite) | não |
| Índices em SpendLogs (`api_key_startTime`, `litellm_call_id`) | 20260823, 20260831120001 | `SELECT 1`: "hand-built", **não** são criados no boot | não; ficam opcionais e manuais (CONCURRENTLY) |
| `total_spend` em `VerificationToken`, `tpd_limit` em Budget/Team/Token | 20260913, 20260916 | aditiva | não (só master key) |
| Tabelas novas: BudgetWindowSpend, ModelAccessGroupBudget, DailyGlobalSpend, ManagedFileContent, AutoRouter*, ShadowEvalFunnel | várias | aditiva | não |
| FK `JWTKeyMapping.token` com ON DELETE CASCADE; índice JWT por issuer | 20260717, 20260915_scope_jwt | troca de constraint/índice | não usamos JWT |
| `LiteLLM_ShadowEvalJob`: `RENAME COLUMN api_key_id → target_id` e DROP INDEX | 20260831000000 | **rename** | não (shadow eval) |
| Colunas em MCP, Agents, Policy, User, ObjectPermission, ManagedObject | várias | aditiva | não |

Tamanho e lock:
- Nenhuma migration faz UPDATE, backfill ou índice síncrono em tabela grande.
- `ADD COLUMN ... DEFAULT const` é instantâneo no Postgres ≥ 11.
- Risco de lock baixo **[código]**.

Rollback para a imagem 1.100:
- O client Prisma antigo ignora colunas e tabelas extras.
- `migrate deploy` deve dizer "No pending migrations" e pular o sanity diff (`0f7b3cadc0:litellm-proxy-extras/.../utils.py:~774-781`).
- A única quebra possível é no código de shadow eval da 1.100, que lê `api_key_id`, e nós não o usamos.
- Conclusão: rollback **provável** **[inferido]**. Ensaiar (§7).

## 4. Funcionalidades que usamos

| Item | Usamos? (evidência) | Muda em 1.104.2? | Impacto | Ação antes do merge |
|---|---|---|---|---|
| `POST /v1/chat/completions` com `model: route:<uuid>`, stream e não-stream | sim (`litellm.adapter.ts:145,266`) | não, quanto à forma | — | smoke por rota |
| `/model/new`, `/model/delete`, `/model/info` (STORE_MODEL_IN_DB) | sim (`litellm-provisioning.adapter.ts:40,110,131`) | rotas presentes **[código]** | — | force-sync no ambiente de teste |
| `model_info.created_at/updated_at` para não-premium | sim (força o sync) | patch nosso 5d0fcec620 **mantido** | — | teste `model_info` passou **[teste]** |
| `/public/litellm_model_cost_map`, `/public/providers/fields` | sim (catálogo e schema de credenciais) | presentes (`public_endpoints.py:388`, `_types.py`) | campos de provider podem ter sido acrescentados | conferir o form de credenciais OCI/Vertex |
| `openai/responses/...` (rotas luna) via ponte chat→Responses | sim | fix CR-049; `reasoning_effort` fora do enum passa a ser repassado (#42452); `verbosity` → `text.verbosity`; provider id e metadata no hidden_params; `reasoning` cai **só** em modelo OpenAI **de catálogo** sem raciocínio (4ef5db7c91). Modelo desconhecido (`gpt-5.6-luna`) ou gpt-5/o-series mantém | payload: `system` no meio da conversa fica no `input` (a mudança desejada) | replay de 1 conversa com follow-up: conferir posição no span |
| Vertex/Gemini | sim | `_transform_system_message` **igual**: todo `system` vai para `system_instruction` **[teste]** | CR-049 **não** se resolve no Gemini | decisão à parte |
| `thought_signature` em `tool_call_id` (`call_<id>__thought__<sig>`) | sim (`litellm-thought-signature.utils.ts`) | separador igual (`factory.py:71`) | — | smoke de tool call Gemini com 2 turnos |
| OCI (`reasoning_effort` maiúsculo, `disable`→`NONE`, `reasoning_tokens`, tool call sem id) | sim | o upstream já tem tudo; código OCI idêntico ao v1.104.2 | — | testes OCI passaram **[teste]**; smoke OCI |
| Fallbacks e roteamento | **nossos**, no gateway (`llm-gateway.service.ts:1584-1610,3291-3318`) | n/a | — | — |
| `drop_params: true` | sim | presente | deixa cair mais params (ex.: `reasoning` em gpt-4o) sem erro | — |
| `cancel_on_disconnect`, `allow_client_side_credentials` | sim (config) | presentes | — | — |
| Callbacks `otel` (success/failure) | sim | `opentelemetry-instrumentation-fastapi` 0.49b0 → 0.54b1 | nomes e atributos de span podem mudar; o collector filtra spans do LiteLLM (`otel-collector.yaml:103-125`) e o `trace.service.ts` lê `error.*` | conferir spans no ambiente de teste |
| Virtual keys, teams, budgets, guardrails, cache, rate limit do LiteLLM | não (só master key) | — | — | — |
| Headers lidos: `x-litellm-response-cost`, `-model-id`, `-call-id`, `-version` | sim | presentes (`common_request_processing.py:1770`) | — | — |
| `x-llm-model-actual`, `x-llm-fallback-used`, `x-llm-cost` | sim | **são nossos** (`llm-proxy.controller.ts:317-334`), não do LiteLLM | — | — |
| Env `MAX_REQUESTS_BEFORE_RESTART`, `STORE_MODEL_IN_DB`, `JSON_LOGS` | sim | lidas | — | — |
| Env `DATABASE_CONNECTION_POOL_LIMIT=5` | setada | **não é lida em nenhuma das duas versões**: o limite vem de `general_settings.database_connection_pool_limit` (default 10) | já hoje é no-op | mover para o config se o limite 5 importar |
| Imagem | — | Wolfi novo, Python 3.13, estágio pgbouncer | tamanho e tempo de boot mudam | medir boot e memória (limite 2Gi) |

## 5. Custo: como calculamos e as gambiarras

Fluxo:
1. O gateway lê `x-litellm-response-cost`, grava em `llm_gateway_requests.cost_usd` e emite `costSource: 'litellm'` (`llm-gateway.service.ts:1652-1676`).
2. O backend não recalcula nada.
3. O staryaai-data recalcula por conta própria, com tokens × catálogo (ADR 0016).

| Gambiarra | Onde | Quebra em 1.104.2? |
|---|---|---|
| Preço por request: `pricing` do approved model injetado no body (só input/output) | `llm-gateway.service.ts:3286`, `litellm-pricing.ts` | Não. Depende do bypass PROXY_ADMIN (3af7a55ebf), **mantido** no merge; teste `test_pricing_field_strip` 17/17 **[teste]** |
| Bypass PROXY_ADMIN para pricing override | fork `litellm_pre_call_utils.py` | mantido; o mecanismo de strip (`_strip_client_pricing_overrides`) segue igual |
| Só input/output por request ⇒ token em cache cobrado como input cheio (sem desconto de cache) | consequência do item acima; o llm-garden aplica `PRICE_OVERRIDE` desde 27/08 (`gwlib.py:105-143`) | **igual** nas duas versões: `completion_cost` com 100k input / 80k cache / 1k output dá 0,108 USD em ambas **[teste]** |
| Whitelist bloqueia o tier `_above_272k_tokens` | `litellm-pricing.ts` | sem mudança nossa |
| Catálogo sincronizado de `/public/litellm_model_cost_map` (input/output/limites/deprecation) | `llm-catalog-sync.service.ts:33-54` | o JSON novo muda **246** entradas de custo nas famílias gemini/gemma/kimi/gpt-5/oci. Gemini 2.5/3.x no tier **padrão**: input, output e cache read **inalterados**; entraram campos `_flex`, `_priority` e `_batches`. Mudam de valor: kimi (fireworks/openrouter) e gemma (deepinfra/nebius) |
| Custo Gemini (Vertex) calculado pelo JSON | — | igual no tier padrão: 0,0109 USD no mesmo uso, nas duas versões **[teste]**. Novo: `trafficType ON_DEMAND_FLEX` → preço flex (d317c5621f); só afeta quem usa flex |
| `reasoning_tokens` | o SDK lê `completion_tokens_details.reasoning_tokens` | campo mantido |

Não testado ponta a ponta: o custo do caminho proxy com preço no body para `openai/responses/*`. O mock do SDK devolve `response_cost=None` nas duas versões. Fica no plano de teste (§7).

## 6. Payload Responses (rotas luna): o que muda no request ao OpenAI

1. Os `system` iniciais vão para `instructions`; `system` e `developer` no meio da conversa ficam no `input`, na posição original. Esse é o objetivo (CR-049). Pode alterar o comportamento de prompts que hoje dependem da concatenação.
2. `reasoning_effort` fora do enum (ex.: `"none"`) passa a ser repassado em vez de descartado (#42452).
3. `verbosity` → `text.verbosity`.
4. `reasoning` é descartado apenas em modelos OpenAI conhecidos sem raciocínio. Para gpt-5.x e para nomes fora do catálogo, nada muda.
5. Não entram na 1.104.2 (estão só no `main`): `prompt_cache_breakpoint` e `safety_identifier` na ponte, e a refatoração de `hidden_params`.

Impacto em custo: o prefixo de prompt pode mudar onde há `system` no meio da conversa, e isso afeta o cache hit do OpenAI nesses turnos **[inferido]**.

## 7. Plano de teste antes do merge

1. **Snapshot** do banco do LiteLLM (o mesmo `LITELLM_DATABASE_URL` do app legado `replicas: 0`).
2. **Imagem de teste por SHA**, sem `:latest`. O workflow só roda em push na staging, então é preciso build manual com tag `test-<sha>`.
3. **Namespace de teste** apontando para uma **cópia restaurada** do snapshot:
   - medir o tempo das migrations;
   - conferir os logs do resolver v2;
   - conferir que nenhum drift foi "corrigido".
4. **Smoke por rota**, a mesma request na imagem antiga e na nova:
   - luna (`openai/responses`) com preço no body;
   - Gemini/Vertex com tool call em 2 turnos (thought signature);
   - OCI com `reasoning_effort`;
   - kimi e gemma.
   
   Comparar status, `x-litellm-response-cost`, `usage` e formato de `tool_call_id`.
5. **CR-049**: um follow-up com `system` no meio da conversa na rota luna. Conferir no span OTEL/debug que vai no `input`.
6. **Gateway**: force-sync (`/model/info` com timestamps), create/delete de rota, `/public/providers/fields` no form.
7. **Ensaio de rollback**: subir a imagem 1.100 contra a cópia migrada; deve subir e servir.
8. **Merge** em janela de baixo tráfego, com acompanhamento de 24h:
   - taxa de erro por rota;
   - custo médio por request contra o baseline;
   - latência e memória do pod.
