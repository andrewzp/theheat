"""Stable reef-system context for Coral Reef Watch regional DHW bundles."""

from __future__ import annotations

from typing import TypedDict


class ReefContextEntry(TypedDict):
    kind: str
    value: str


REEF_CONTEXT: dict[str, tuple[ReefContextEntry, ...]] = {
    "austral_islands": (
        {
            "kind": "current_system",
            "value": "the Austral Islands sit on French Polynesia's cooler southern reef edge in the South Pacific",
        },
        {
            "kind": "notable_history",
            "value": "French Polynesian reefs were exposed to broad South Pacific heat stress during the 2015-2016 El Nino bleaching event",
        },
        {
            "kind": "ecosystem_note",
            "value": "isolated high-island and atoll reefs connect shallow lagoons to steep oceanic drop-offs",
        },
    ),
    "chagos_archipelago": (
        {
            "kind": "current_system",
            "value": "the Chagos Archipelago is a central Indian Ocean atoll chain around the Great Chagos Bank",
        },
        {
            "kind": "notable_history",
            "value": "the 1998 Indian Ocean bleaching event caused major coral mortality across Chagos reefs before monitored recovery",
        },
        {
            "kind": "ecosystem_note",
            "value": "remote atolls and submerged banks make Chagos one of the Indian Ocean's largest reef systems",
        },
    ),
    "costa_rica_pacific": (
        {
            "kind": "current_system",
            "value": "Costa Rica's Pacific reefs sit in the eastern tropical Pacific, where seasonal upwelling and warm-pool shifts meet",
        },
        {
            "kind": "notable_history",
            "value": "strong El Nino events have repeatedly pushed eastern Pacific reef temperatures into bleaching stress",
        },
        {
            "kind": "ecosystem_note",
            "value": "these reefs are patchy, high-contrast habitats between upwelling-influenced gulfs and tropical offshore water",
        },
    ),
    "east_java_bali": (
        {
            "kind": "current_system",
            "value": "East Java and Bali sit along the Indonesian Throughflow route between the Pacific and Indian oceans",
        },
        {
            "kind": "notable_history",
            "value": "Indonesian reefs saw widespread heat stress during the 2010 and 2016 regional bleaching events",
        },
        {
            "kind": "ecosystem_note",
            "value": "reef slopes, straits, and island channels make this a high-exchange part of the Coral Triangle region",
        },
    ),
    "fiji": (
        {
            "kind": "current_system",
            "value": "Fiji's reef system includes the Great Sea Reef along Vanua Levu and the Great Astrolabe Reef around Kadavu",
        },
        {
            "kind": "notable_history",
            "value": "South Pacific marine heatwaves in 2016 and 2017 brought bleaching stress to parts of Fiji",
        },
        {
            "kind": "ecosystem_note",
            "value": "barrier reefs, lagoon passages, mangroves, and village fishing grounds make reef condition a coastal-systems signal",
        },
    ),
    "galapagos": (
        {
            "kind": "current_system",
            "value": "Galapagos reefs sit where the Cromwell Current and other upwelling systems bring cold, nutrient-rich water to the equator",
        },
        {
            "kind": "notable_history",
            "value": "the 1982-1983 and 1997-1998 El Nino events caused severe coral losses around the Galapagos",
        },
        {
            "kind": "ecosystem_note",
            "value": "corals there live inside a system known for sharp swings between upwelling cool water and El Nino warmth",
        },
    ),
    "gilbert_islands": (
        {
            "kind": "current_system",
            "value": "the Gilbert Islands are Kiribati atolls near the equator in the central Pacific warm-pool belt",
        },
        {
            "kind": "notable_history",
            "value": "central Pacific heat stress during the 2015-2016 El Nino exposed Kiribati reefs to bleaching conditions",
        },
        {
            "kind": "ecosystem_note",
            "value": "low coral atolls depend on reef rims for wave buffering, lagoon habitat, and coastal fisheries",
        },
    ),
    "great_nicobar": (
        {
            "kind": "current_system",
            "value": "Great Nicobar sits at the Andaman Sea and Bay of Bengal gateway, close to the eastern Indian Ocean monsoon system",
        },
        {
            "kind": "notable_history",
            "value": "the 2004 Indian Ocean earthquake and tsunami reshaped parts of the Nicobar reef and shoreline system",
        },
        {
            "kind": "ecosystem_note",
            "value": "fringing reefs, seagrass, mangroves, and steep island slopes sit close together around the Nicobar Islands",
        },
    ),
    "kenya": (
        {
            "kind": "current_system",
            "value": "Kenya's reefs are western Indian Ocean fringing reefs influenced by the East African Coastal Current",
        },
        {
            "kind": "notable_history",
            "value": "the 1998 western Indian Ocean bleaching event caused major coral losses on Kenyan reefs",
        },
        {
            "kind": "ecosystem_note",
            "value": "reef lagoons and seagrass beds support nearshore fisheries from the Lamu coast to the Mombasa marine parks",
        },
    ),
    "nauru": (
        {
            "kind": "current_system",
            "value": "Nauru is an isolated raised coral island in the central Pacific with a narrow reef flat around a steep oceanic slope",
        },
        {
            "kind": "notable_history",
            "value": "phosphate mining transformed much of Nauru's interior, leaving the coastal reef fringe as a concentrated marine habitat",
        },
        {
            "kind": "ecosystem_note",
            "value": "the island has little lagoon area, so reef-flat stress is a direct coastal exposure signal",
        },
    ),
    "samoas": (
        {
            "kind": "current_system",
            "value": "the Samoan archipelago sits in the South Pacific trade-wind belt near the South Equatorial Current",
        },
        {
            "kind": "notable_history",
            "value": "American Samoa reefs experienced documented bleaching during the 2015-2016 El Nino marine heatwave",
        },
        {
            "kind": "ecosystem_note",
            "value": "fringing reefs and reef flats protect villages, lagoons, and coastal fisheries across the volcanic island chain",
        },
    ),
    "solomon_islands": (
        {
            "kind": "current_system",
            "value": "the Solomon Islands sit on the western Pacific edge of the Coral Triangle, between warm-pool water and island passages",
        },
        {
            "kind": "notable_history",
            "value": "the 2007 Solomon Islands earthquake and tsunami lifted and damaged reef flats in parts of Western Province",
        },
        {
            "kind": "ecosystem_note",
            "value": "reef channels, lagoons, mangroves, and seagrass beds make the archipelago a high-diversity reef seascape",
        },
    ),
    "southern_borneo": (
        {
            "kind": "current_system",
            "value": "southern Borneo's reefs sit along the Java Sea and Makassar Strait margin of Indonesia's island-sea system",
        },
        {
            "kind": "notable_history",
            "value": "Indonesian reef surveys recorded regional bleaching during the 2010 and 2016 marine heat-stress events",
        },
        {
            "kind": "ecosystem_note",
            "value": "nearshore reefs there are shaped by island passages, monsoon winds, and sediment from large tropical watersheds",
        },
    ),
    "west_kalimanta": (
        {
            "kind": "current_system",
            "value": "West Kalimantan's reefs face the Karimata Strait and South China Sea side of Indonesian Borneo",
        },
        {
            "kind": "notable_history",
            "value": "Borneo's coastal reefs have been included in Indonesia-wide bleaching reports during recent regional heat events",
        },
        {
            "kind": "ecosystem_note",
            "value": "river-influenced nearshore water makes these reefs part of a turbid coastal shelf, not a clear oceanic atoll system",
        },
    ),
    "western_madagascar": (
        {
            "kind": "current_system",
            "value": "western Madagascar's reefs face the Mozambique Channel, where eddies and warm western Indian Ocean water interact",
        },
        {
            "kind": "notable_history",
            "value": "the 1998 western Indian Ocean bleaching event affected Madagascar and neighboring channel reefs",
        },
        {
            "kind": "ecosystem_note",
            "value": "reef flats, mangroves, and seagrass support coastal fisheries along Madagascar's west coast",
        },
    ),
}


def reef_context_facts(region_id: str, *, limit: int = 3) -> list[dict[str, str]]:
    """Return capped StoryBundle facts for a CRW region id."""

    entries = REEF_CONTEXT.get(region_id, ())
    return [
        {
            "label": "reef_context",
            "kind": entry["kind"],
            "value": entry["value"],
        }
        for entry in entries[:limit]
    ]
