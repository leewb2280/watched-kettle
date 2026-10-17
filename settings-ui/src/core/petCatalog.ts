import type { PetCatalogEntry } from "../types";

export const petTabs = ["외형·표시", "동작·화면"];

// Mirrors watched_kettle.pet.catalog.order_pet_entries: entries arrive in name
// order, ranked IDs come first in custom mode and the rest keep name order.
export function orderedCatalog(
  entries: PetCatalogEntry[],
  sort: string,
  order: string[],
) {
  if (sort !== "custom") return entries;
  const rank = new Map(order.map((id, index) => [id, index]));
  return [
    ...entries
      .filter((entry) => rank.has(entry.id))
      .sort((a, b) => rank.get(a.id)! - rank.get(b.id)!),
    ...entries.filter((entry) => !rank.has(entry.id)),
  ];
}
