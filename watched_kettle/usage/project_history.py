"""Account-scoped project navigation; no UI state or persistent names."""

from watched_kettle.usage.conversation_models import (
    UNCLASSIFIED_PROJECT_KEY,
    sort_projects,
)


class ProjectHistory:
    def __init__(self, service):
        self.service = service
        self.reset()

    def reset(self):
        self.enabled = False
        self.search = ""
        self.order = "recent"
        self.custom: tuple[str, ...] = ()
        self.offset = 0
        self.selected = ""

    def valid(self, account, generation):
        s = self.service
        return (
            bool(s.snapshot.account_hash)
            and not s.snapshot.account_checking
            and (
                account is None
                or (
                    account == s.snapshot.account_hash
                    and generation == s.account.generation
                )
            )
        )

    def keys(self, order=None):
        rows = self.service.repository.project_summaries(
            self.service.snapshot.account_hash
        )
        return tuple(
            r.project_key for r in sort_projects(rows, order or self.order, self.custom)
        )

    @staticmethod
    def _normalize_custom(custom):
        custom = tuple(custom)
        keys = tuple(
            dict.fromkeys(
                str(key)
                for key in custom
                if isinstance(key, str) and key not in {"none", "unknown"}
            )
        )
        if any(key in {"none", "unknown"} for key in custom):
            if UNCLASSIFIED_PROJECT_KEY not in keys:
                keys += (UNCLASSIFIED_PROJECT_KEY,)
        return keys

    def query(
        self,
        search="",
        order="recent",
        offset=0,
        custom=None,
        account=None,
        generation=None,
    ):
        if not self.valid(account, generation):
            return False
        previous_order = self.order
        if custom is not None:
            self.custom = self._normalize_custom(custom)
        if order == "custom" and not self.custom:
            self.custom = self.keys(previous_order)
        changed_search = self.search != str(search).strip()[:200]
        self.enabled = True
        self.search = str(search).strip()[:200]
        self.order = order if order in ("recent", "name", "custom") else "recent"
        self.offset = max(0, min(int(offset), self.offset + 100))
        if changed_search:
            self.offset = 0
            self.service._conversation_offset = 0
        self.service._conversation_mode = True
        self.service._conversation_search = self.search
        self.service.conversation_catalog.start()
        self.publish()
        return True

    def select(self, key, account=None, generation=None):
        if not self.valid(account, generation) or key not in self.keys():
            return False
        self.selected = key
        self.service._conversation_offset = 0
        self.publish()
        return True

    def move(
        self, key, direction=0, target="", before=True, account=None, generation=None
    ):
        if not self.valid(account, generation) or self.search or self.order != "custom":
            return False
        keys = list(self.keys("custom"))
        if key not in keys:
            return False
        previous_keys = tuple(keys)
        keep_unclassified_last = (
            key != UNCLASSIFIED_PROJECT_KEY
            and self.custom
            and self.custom[-1] == UNCLASSIFIED_PROJECT_KEY
            and UNCLASSIFIED_PROJECT_KEY in keys
        )
        old = keys.index(key)
        if target:
            if target not in keys or target == key:
                return False
            keys.remove(key)
            index = keys.index(target) + (0 if before else 1)
        else:
            index = max(0, min(len(keys) - 1, old + (1 if direction > 0 else -1)))
            keys.remove(key)
        keys.insert(index, key)
        if keep_unclassified_last:
            keys.remove(UNCLASSIFIED_PROJECT_KEY)
            keys.append(UNCLASSIFIED_PROJECT_KEY)
        if tuple(keys) == previous_keys:
            return False
        index = keys.index(key)
        # Keep absent IDs so temporary metadata loss does not destroy a saved order.
        self.custom = tuple(keys) + tuple(k for k in self.custom if k not in keys)
        self.offset = index // 100 * 100
        self.publish()
        return True

    def values(self, account):
        repo = self.service.repository
        if self.order == "custom":
            keys = self.keys("name")
            added = tuple(k for k in keys if k not in self.custom)
            if self.custom and self.custom[-1] == UNCLASSIFIED_PROJECT_KEY:
                self.custom = self.custom[:-1] + added + (UNCLASSIFIED_PROJECT_KEY,)
            else:
                self.custom += added
        page = repo.query_projects(
            account, self.search, self.order, self.custom, self.offset
        )
        if not page.records and self.offset:
            self.offset = max(0, (page.total_count - 1) // 100 * 100)
            page = repo.query_projects(
                account, self.search, self.order, self.custom, self.offset
            )
        if self.selected not in {r.project_key for r in page.records}:
            self.selected = page.records[0].project_key if page.records else ""
            self.service._conversation_offset = 0
        return dict(
            project_mode=True,
            projects=page.records,
            project_search=self.search,
            project_order=self.order,
            project_custom_order=self.custom,
            project_offset=self.offset,
            projects_has_more=page.has_more,
            project_count=page.total_count,
            selected_project_key=self.selected,
        )

    def publish(self):
        self.service._publish(
            **self.service._history_values(self.service.snapshot.account_hash)
        )
