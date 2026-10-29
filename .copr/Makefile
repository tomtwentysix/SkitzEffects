# Called by COPR as: make -f .copr/Makefile srpm outdir=<dir> spec=<spec>
top := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
version := $(shell sed -n 's/^Version:[[:space:]]*//p' $(top)/packaging/skitz-effects.spec)

srpm:
	tar -C $(top) --exclude=__pycache__ --transform 's,^,skitz-effects-$(version)/,' \
		-czf $(outdir)/skitz-effects-$(version).tar.gz skitz_effects data packaging README.md LICENSE
	rpmbuild -bs --define "_sourcedir $(outdir)" --define "_srcrpmdir $(outdir)" \
		$(top)/packaging/skitz-effects.spec
