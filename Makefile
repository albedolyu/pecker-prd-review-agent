.PHONY: help install install-deps install-hooks check-hooks dev-api dev-web test test-py test-web test-e2e-local lint kb-lint build secrets check-env eval-consistency init-acl clean

help:  ## 列出所有命令
	@echo "Pecker 常用命令 (运行 make <target>):"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: install-deps install-hooks  ## 一次性 setup: pip + 前端 + git hooks (开发者首次进项目跑这条)
	@echo ""
	@echo "[make install] 完成."
	@echo "[make install] 下一步:"
	@echo "  1. 配 .env: bash scripts/gen-secrets.sh > .env (然后填 FEISHU / API_KEY 等)"
	@echo "  2. 启后端: make dev-api"
	@echo "  3. 启前端: make dev-web"

install-deps:  ## 仅装 Python + 前端依赖 (不装 hooks)
	pip install -r requirements.txt
	cd web && pnpm install

install-hooks:  ## 装 git pre-push hook (跨平台, 走 Python 实现)
	@python scripts/install_git_hooks.py || \
		echo "[make install-hooks] WARN: hook 安装失败 (不是 git repo / 已存在不同内容); 不阻塞 make install"

check-hooks:  ## 检查 hook 是否漂移 (CI 用, 漂移返回 1)
	python scripts/install_git_hooks.py --check

dev-api:  ## 启动后端 FastAPI (uvicorn :8000)
	uvicorn api.main:app --reload --port 8000 --host 0.0.0.0

dev-web:  ## 启动前端 Next.js (:3000)
	cd web && pnpm dev

test:  ## 跑 pytest + 前端 vitest
	python -m pytest tests/ -q
	cd web && pnpm test

test-py:  ## 只跑 Python 单测
	python -m pytest tests/ -q

test-web:  ## 只跑前端单测
	cd web && pnpm test

test-e2e-local:  ## 本地 e2e, playwright.webServer 自动起停 next (需先 pnpm build)
	cd web && pnpm exec playwright test --project chrome-local

lint:  ## ESLint + doc_coherence
	cd web && pnpm run lint
	python scripts/doc_coherence.py --check all

kb-lint:  ## 知识库一致性扫描 (Kakapo + doc_coherence)
	python scripts/doc_coherence.py --check all
	python kakapo_dream.py --wiki-path shared-wiki --scan-only

build:  ## 前端生产构建
	cd web && pnpm build

init-acl:  ## 为新 workspace 写 .pecker_acl.json (用法 WS=workspace-xxx OWNER=alice [READERS=bob,carol])
	@if [ -z "$(WS)" ] || [ -z "$(OWNER)" ]; then \
		echo "用法: make init-acl WS=workspace-xxx OWNER=alice [READERS=bob,carol]"; \
		exit 1; \
	fi
	@if [ ! -d "$(WS)" ]; then echo "workspace 不存在: $(WS)"; exit 1; fi
	@python -c "import json, sys; readers = [r.strip() for r in '$(READERS)'.split(',') if r.strip()]; json.dump({'owner': '$(OWNER)', 'readers': readers, '_note': 'Initialized by make init-acl'}, open('$(WS)/.pecker_acl.json', 'w'), ensure_ascii=False, indent=2)"
	@echo "✓ 写入 $(WS)/.pecker_acl.json (owner=$(OWNER), readers=$(READERS))"

secrets:  ## 生成新的 SIGNATURE_SECRET / JWT_SECRET 到 stdout (`make secrets >> .env` 追加)
	bash scripts/gen-secrets.sh

check-env:  ## 校验现有 .env 里 secret 强度
	bash scripts/gen-secrets.sh --check .env

eval-consistency:  ## 跑一致性评测 3 轮, 用法: make eval-consistency PRD=workspace-foo/prd/xxx.md
	@test -n "$(PRD)" || (echo "用法: make eval-consistency PRD=<path-to-prd.md>"; exit 1)
	python eval/consistency_eval.py "$(PRD)" --runs 3

clean:  ## 清理 Python / pytest 缓存
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
