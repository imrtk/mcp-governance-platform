# vCenter Tag Detection Fix

## Problem
`_vm_has_tag` fonksiyonu `content.taggingManager.ListTagsForObject(vm)` API'sini kullanıyor,
bu API bu vCenter sürümünde çalışmıyor. Monitor-agent `exclude_tag="monitor-ignore"` göndermesine
rağmen VM'ler filtrelenemiyor.

## Çözüm
VM Annotation (Notes) alanını öncelikli olarak kullan, tagging API'yi fallback olarak bırak.

## Değişecek Dosyalar

### 1. `mcp_servers/vcenter_mcp.py`

**a) `_vm_has_tag` fonksiyonu** — önce annotation kontrolü, sonra tagging API:
```python
def _vm_has_tag(vm, tag_name: str) -> bool:
    annotation = getattr(vm.summary.config, 'annotation', None) or ''
    annotation_tags = [t.strip().lower() for t in annotation.replace('\n', ',').split(',') if t.strip()]
    if tag_name.lower() in annotation_tags:
        return True
    try:
        content = _get_content()
        if hasattr(content, 'taggingManager') and content.taggingManager:
            tagging = content.taggingManager
            tags = tagging.ListTagsForObject(vm)
            return any(t.name == tag_name for t in tags)
    except Exception:
        pass
    return False
```

**b) `vcenter_vm_has_tag` tool'u** — teşhis amaçlı, TOOLS listesine eklenecek

**c) `_vm_has_tag_tool` fonksiyonu** — JSON döndürür (vm, has_tag, annotation, tagging_api_available)

**d) TOOL_FUNCS** — `"vcenter_vm_has_tag": _vm_has_tag_tool` eklenecek

### 2. `agents/vcenter_agent.py`

**a) TOOLS listesi** — `vcenter_vm_has_tag` tool tanımı

**b) `_vm_has_tag` fonksiyonu** — MCP'ye çağrı yapar

**c) TOOL_FUNCS** — `"vcenter_vm_has_tag": _vm_has_tag`

### 3. Test
```bash
curl -s http://localhost:8006/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"vcenter_vm_has_tag","arguments":{"name":"debian13","tag_name":"monitor-ignore"}},"id":1}' | jq .
```

### 4. Kullanıcı Talimatı
vCenter'da VM → Edit Settings → Notes alanına `monitor-ignore` yazılacak.
