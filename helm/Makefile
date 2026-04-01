.PHONY: lint test test-installer unittest test-services test-all help

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

lint: ## Run helm lint on the chart
	helm lint .

test: ## Run chart tests
	./tests/test-chart-lint.sh
	./tests/test-install-script.sh
	./tests/test-third-party-pack-installer.sh

test-installer: ## Validate install script safety defaults
	./tests/test-install-script.sh
	./tests/test-third-party-pack-installer.sh

unittest: ## Run helm-unittest suites
	helm unittest . --file 'tests/unittest/*_test.yaml'

test-services: ## Test services deployment (requires cluster access)
	./tests/test-services.sh

test-all: lint test unittest ## Run all tests
