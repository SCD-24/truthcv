import { describe, expect, it } from "vitest";
import { formatRunTimes, isValidRunTime, WEEKDAYS } from "./schedule";

describe("schedule helpers", () => {
  it("validates HH:MM", () => {
    expect(isValidRunTime("09:00")).toBe(true);
    expect(isValidRunTime("23:59")).toBe(true);
    expect(isValidRunTime("9:00")).toBe(false);
    expect(isValidRunTime("24:00")).toBe(false);
    expect(isValidRunTime("09:60")).toBe(false);
  });
  it("lists seven ordered weekdays keyed for the API", () => {
    expect(WEEKDAYS.map((d) => d.key)).toEqual(["mon","tue","wed","thu","fri","sat","sun"]);
  });
  it("formats run times", () => {
    expect(formatRunTimes(["09:00", "15:00"])).toBe("09:00 and 15:00");
    expect(formatRunTimes(["07:00"])).toBe("07:00");
  });
});
