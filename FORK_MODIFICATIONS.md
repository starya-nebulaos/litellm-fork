# LiteLLM Fork Modifications

Modificações feitas pelo time Starya/NebulaOS no fork. Use como referência ao resolver conflitos durante sync com upstream.

---

## Resumo

| Área | Arquivos | Autor |
|------|----------|-------|
| CI/CD OCIR | `.github/workflows/build-ocir.yml` | Nicholas |
| OCI GenAI | `litellm/llms/oci/*` | Federico |
| OCI Tool Calls | `litellm/llms/oci/*` | Thiago |
| OCI reasoning_effort | `litellm/llms/oci/*`, `litellm/main.py` | Thiago, Federico |
| Model Timestamps | `litellm/proxy/proxy_server.py` | Thiago |
| Pricing Override Bypass | `litellm/proxy/litellm_pre_call_utils.py` | Thiago |

---

## 1. CI/CD - Build OCIR

**Autor**: Nicholas  
**Arquivos**: `.github/workflows/build-ocir.yml`

Workflow para buildar e fazer push para Oracle Cloud Infrastructure Registry.

- Trigger: push em `litellm_internal_staging`
- Imagem: `sa-saopaulo-1.ocir.io/gr4yakoorvrm/litellm:latest`

---

## 2. OCI GenAI - Integração Completa

**Autor**: Federico  
**PR Upstream**: #25177

### Arquivos Modificados

- `litellm/llms/oci/chat/transformation.py` - Refatorado
- `litellm/llms/oci/chat/cohere.py` - Novo
- `litellm/llms/oci/chat/generic.py` - Novo
- `litellm/llms/oci/common_utils.py` - Expandido
- `litellm/llms/oci/embed/transformation.py` - Embeddings
- `litellm/types/llms/oci.py` - Tipos
- `litellm/utils.py` - Removeu branch morto OCI
- `litellm/llms/custom_httpx/llm_http_handler.py` - Streaming fixes
- `model_prices_and_context_window.json` - Preços OCI

### Mudanças Principais

- Split de `transformation.py` em `cohere.py` e `generic.py`
- Suporte a embeddings
- Fix streaming com signed body
- Catálogo de modelos OCI expandido

### Resolução de Conflitos

Upstream pode modificar `litellm/llms/oci/*`. Nosso refactor dividiu o arquivo - verificar se mudanças upstream pertencem ao cohere ou generic.

---

## 3. OCI Tool Calls - Missing ID Fix

**Autor**: Thiago  
**Commit**: `ebccfbfa65`

Fix para tool call ID faltando em respostas non-streaming OCI.

---

## 4. OCI reasoning_effort

**Autores**: Thiago, Federico  
**Arquivos**: `litellm/llms/oci/*`, `litellm/main.py`

- Converte reasoning_effort para uppercase (OCI API requirement)
- Mapeia 'disable' para 'NONE'
- Extrai reasoning_tokens da resposta

---

## 5. Model Timestamps

**Autor**: Thiago  
**Commit**: `5d0fcec620`  
**Arquivo**: `litellm/proxy/proxy_server.py`

Expõe `created_at`/`updated_at` em model_info para todos os usuários.

---

## 6. PROXY_ADMIN Pricing Override Bypass

**Autor**: Thiago  
**Commit**: `3af7a55ebf`  
**Arquivo**: `litellm/proxy/litellm_pre_call_utils.py`

Master key (PROXY_ADMIN) tem bypass automático para enviar parâmetros de pricing customizado sem precisar de `allow_client_pricing_override` no metadata.

```python
def _key_or_team_allows_client_pricing_override(...):
    if user_api_key_dict.user_role == LitellmUserRoles.PROXY_ADMIN:
        return True
    ...
```

---

## Procedimento de Sync

```bash
git fetch origin main
git checkout -b sync/upstream-YYYY-MM-DD fork/litellm_internal_staging
git merge origin/main
# Resolver conflitos usando este doc
make test-unit
git push fork sync/upstream-YYYY-MM-DD
```

---

*Atualizado: 2026-06-17*
