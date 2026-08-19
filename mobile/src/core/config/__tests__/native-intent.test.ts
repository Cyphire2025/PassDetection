import { redirectSystemPath } from "../../../app/+native-intent";

const token = "A_secure-one-time_activation_token_1234567890";

describe("native activation intent", () => {
  it("accepts only the exact verified HTTPS activation URL", () => {
    expect(
      redirectSystemPath({
        path: `https://tech.gctravels.com/gc/activate?token=${token}`,
        initial: true,
      }),
    ).toBe(`/activate?token=${token}`);

    expect(
      redirectSystemPath({
        path: `https://tech.gctravels.com/gc/activate?token=${token}`,
        initial: false,
      }),
    ).toBe(`/activate?token=${token}`);
  });

  it.each([
    `groupcompanion://activate?token=${token}`,
    `http://tech.gctravels.com/gc/activate?token=${token}`,
    `https://tech.gctravels.com.evil.example/gc/activate?token=${token}`,
    `https://evil.example/gc/activate?token=${token}`,
    `https://tech.gctravels.com/activate?token=${token}`,
    `https://tech.gctravels.com/gc/activate/?token=${token}`,
    `https://tech.gctravels.com/gc/activate?token=${token}#fragment`,
    `https://tech.gctravels.com/gc/activate?token=${token}&next=/documents`,
    `https://tech.gctravels.com/gc/activate?token=${token}&token=${token}`,
    "https://tech.gctravels.com/gc/activate?token=short",
    `/gc/activate?token=${token}`,
    "not a URL",
  ])("rejects an unverified or ambiguous credential path: %s", (path) => {
    expect(redirectSystemPath({ path, initial: true })).toBe("/");
  });
});
