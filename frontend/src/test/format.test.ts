import { describe, expect, it } from "vitest";
import { errorMessage } from "../api/client";
import { compactNumber } from "../components/charts";
import { parseRateInput, parseWonInput, won } from "../lib/format";

describe("금액 표시·입력", () => {
  it("문자열 금액을 부동소수점 변환 없이 천 단위로 표시한다", () => {
    expect(won("12345678901234567")).toBe("12,345,678,901,234,567원");
    expect(won("1000.50")).toBe("1,000.50원");
    expect(won(null)).toBe("-");
  });
  it("원 단위 입력: 쉼표·'원' 허용, 소수·문자 거부", () => {
    expect(parseWonInput("1,000,000원")).toBe("1000000");
    expect(parseWonInput("12abc")).toBeNull();
    expect(parseWonInput("100.5")).toBeNull();
    expect(parseWonInput("")).toBeNull();
  });
  it("비율 입력", () => {
    expect(parseRateInput("87.745%")).toBe("87.745");
    expect(parseRateInput("-0.5")).toBe("-0.5");
    expect(parseRateInput("팔십")).toBeNull();
  });
  it("축 눈금 짧은 표기", () => {
    expect(compactNumber(800_000_000)).toBe("8억");
    expect(compactNumber(2_500_000_000)).toBe("25억");
    expect(compactNumber(35_000)).toBe("4만");
    expect(compactNumber(28)).toBe("28");
  });
});

describe("API 오류 메시지", () => {
  it("서버 메시지를 그대로 쓰고, 연결 실패·서버 오류는 안내 문구로 바꾼다", () => {
    expect(errorMessage(400, { message: "기초금액이 없습니다.", field: "base_amount" })).toEqual({ message: "기초금액이 없습니다.", field: "base_amount" });
    expect(errorMessage(409, { detail: { message: "이미 올린 파일입니다.", document_id: 3 } }).message).toBe("이미 올린 파일입니다.");
    expect(errorMessage(422, { detail: [{ loc: ["body", "bid_amount"], msg: "invalid" }] }).message).toContain("bid_amount");
    expect(errorMessage(0, null).message).toContain("서버에 연결할 수 없습니다");
    expect(errorMessage(503, "Service Unavailable").message).toContain("503");
  });
});
