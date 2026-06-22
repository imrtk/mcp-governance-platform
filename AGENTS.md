# Session Context

## Mimari
- **Benim ortam (airgap)**: Geliştirme ortamı, DigitalOcean var, vCenter yok
- **Kullanıcı ortamı**: Test ortamı, vCenter var, DO yok
- İş akışı: Ben kod yaz → Github push → Kullanıcı zip indir → test et → sonuç bildir

## vCenter Entegrasyon Durumu
- `mcp_servers/vcenter_mcp.py` - vCenter MCP sunucusu (port 8006) ✅
- `agents/vcenter_agent.py` - vCenter agent (port 8016) ✅
- `agents/orchestrator.py` - vcenter-agent tool'ları prompt'a eklendi ✅
- `registry/api.py` - vcenter-mcp (id:9) ve vcenter-agent (id:10) kayıtlı ✅
- `.env.example` - VCENTER_* değişkenleri mevcut ✅
- `start.sh` - vcenter_mcp (8006) ve vcenter_agent (8016) başlatılıyor ✅
- `agents/monitor_agent.py` - vCenter VM izleme eklendi (kapalı VM'leri orchestrator'a bildirir) ✅
- Bug fix: `vcenter_mcp.py` _vm_summary'de tanımsız `e` düzeltildi ✅
- README güncellendi ✅

## Yapılacaklar / Bilinen Eksikler
- vCenter MCP için Dockerfile gerekebilir
- pyproject.toml'a pyvmomi bağımlılığı eklenmiş mi kontrol et
- Diğer agent'lar (do, sysadmin, devops, secops, monitor) ve MCP'ler (file, shell, debian, do) registry'den çıkarıldı, geçici olarak devre dışı
- start.sh sadece vcenter-mcp + orchestrator + vcenter-agent + gateway başlatacak şekilde sadeleştirildi
- Orchestrator prompt'u sadece vcenter-agent örnekleri içerecek şekilde güncellendi

## Commit Geçmişi (son)
- `8040b81` - orchestrator prompt'a vcenter-agent tool'ları eklendi
- `5110e19` - vCenter entegrasyonu (vcenter-mcp + vcenter-agent)
