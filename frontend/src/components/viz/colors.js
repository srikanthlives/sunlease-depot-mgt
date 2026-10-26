// Activity-type colours: validated categorical slots 1-4 (adjacent CVD-safe order).
export const TYPE_COLOR = {
  PASSENGER_TRIP: "#2a78d6",
  NON_REVENUE_MOVEMENT: "#eb6834",
  CHARGING: "#1baf7a",
  LAYOVER: "#eda100",
  // off-service block: neutral grey so it reads as "not in service"
  HALT: "#7b8494",
};
export const TYPE_SHORT = { PASSENGER_TRIP: "Trip", NON_REVENUE_MOVEMENT: "Movement", CHARGING: "Charging", LAYOVER: "Layover", HALT: "Halt (not in cycle)" };
export const STATUS = { critical: "#d03b3b", warning: "#fab219", good: "#0ca30c" };
export const INK = { primary: "#12203A", secondary: "#52514e", muted: "#8a8f98", grid: "#e5e8ee", surface: "#ffffff" };
