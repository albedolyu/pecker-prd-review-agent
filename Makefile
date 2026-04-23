.PHONY: help install dev-api dev-web test test-py test-web lint kb-lint build secrets check-env eval-consistency clean

help:  ## 列出所有命令
	@echo "Pecker 常用命令 (运行 make <target>):"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## 安装 Python + 前端依赖
	pip install -r requirements.txt
	cd web && pnpm install

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

lint:  ## ESLint + doc_coherence
	cd web && pnpm run lint
	python scripts/doc_coherence.py --check all

kb-lint:  ## 知识库一致性扫描 (Kakapo + doc_coherence)
	python scripts/doc_coherence.py --check all
	python kakapo_dream.py --wiki-path shared-wiki --scan-only

build:  ## 前端生产构建
	cd web && pnpm build

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
