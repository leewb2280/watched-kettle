export type Values = Record<string, any>;
export type Page =
  | "home"
  | "pet"
  | "bubble"
  | "widget"
  | "usage"
  | "activity"
  | "integration"
  | "app";
export type Control = {
  key: string;
  label: string;
  value: any;
  kind: string;
  group: string;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  options?: { value: any; label: string }[];
  presets?: { value: number; label: string }[];
  description?: string;
  effectiveValue?: number;
  fallbackLabel?: string;
  disabled?: boolean;
};
export type SettingsSnapshot = {
  version: string;
  revision: number;
  epoch: number;
  edition: "pet-only" | "pet-assistant";
  pet: Values;
  controls: Control[];
  bubbleControls: Control[];
  appearance: Values;
  startup: Values;
  animations: { label: string; value: string }[];
  update: UpdateState;
};
// watched_kettle/application/update_check.py UpdateService.snapshot().
export type UpdateState = {
  state:
    | "idle"
    | "checking"
    | "current"
    | "available"
    | "downloading"
    | "preparing"
    | "installing"
    | "error";
  version: string;
  page_url: string;
  received: number;
  total: number;
  message: string;
  can_install: boolean;
  retry: "" | "check" | "download";
  // The saved setting, added by CoreSettingsAdapter.snapshot().
  auto_check: boolean;
};
export type Route = {
  page: Page;
  section?: string;
  navigationId?: string;
  notice?: Values;
  filter?: string;
};
export type CommandOptions = {
  // The caller shows the error itself (e.g. inside a modal), so skip the banner.
  inline?: boolean;
  // Read-only queries (paging, selection) leave the save status untouched.
  quiet?: boolean;
};
export type Shell = {
  snapshot: SettingsSnapshot;
  command: (
    method: string,
    args?: Values,
    options?: CommandOptions,
  ) => Promise<any>;
  refresh: () => Promise<void>;
  navigate: (page: Page) => void;
  notify: (text: string) => void;
  reportError: (error: unknown) => void;
  visible: boolean;
  eventVersion: number;
  route: Route | null;
};
declare global {
  const __ASSISTANT__: boolean;
  interface Window {
    settings?: {
      request: (method: string, args?: Values) => Promise<any>;
      file: (
        purpose: "import" | "export" | "pet",
        kind?: string,
      ) => Promise<any>;
      onEvent: (
        listener: (value: { event: string; data: any }) => void,
      ) => () => void;
      ready: () => Promise<any>;
    };
  }
}

export type PetCatalogEntry = {
  id: string;
  name: string;
  description: string;
  thumbnail: string;
  source: "user" | "bundled" | "external";
  canDelete: boolean;
  deletionReason: string;
};
export type PetCatalog = {
  entries: PetCatalogEntry[];
  order: string[];
  hidden: string[];
  sort: "name" | "custom";
  revision: number;
  petId: string;
};
export type PetTrashEntry = {
  trashId: string;
  id: string;
  name: string;
  deletedAt: string;
  bytes: number;
  thumbnail: string;
  state: "moving" | "trashed" | "restoring" | "deleting";
};
export type PetTrashCatalog = {
  entries: PetTrashEntry[];
  offset: number;
  total: number;
  totalBytes: number;
  issues: string[];
  revision: number;
  petId: string;
};

export type PetBatchAction = "move" | "restore" | "delete";
export type PetBatchResult = {
  id: string;
  name: string;
  status: "pending" | "succeeded" | "failed" | "notStarted";
  code: string;
  message: string;
  trashId?: string;
};
export type PetBatchJob = {
  undoIds: string[];
  jobId: string;
  operationKey: string;
  action: PetBatchAction;
  state: "running" | "completed" | "cancelled" | "failed";
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
  message: string;
  code: string;
  results: PetBatchResult[];
};
