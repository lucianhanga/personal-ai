import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import * as api from "./api";
import { LocalizedImage } from "./LocalizedImage";

// We mock the api module functions used by LocalizedImage.
vi.mock("./api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return {
    ...original,
    localizeImage: vi.fn(),
    allowEgressHost: vi.fn(),
  };
});

const mockLocalizeImage = vi.mocked(api.localizeImage);
const mockAllowEgressHost = vi.mocked(api.allowEgressHost);

const TOKEN = "test-token";
const URL = "https://upload.wikimedia.org/image.png";
const DATA_URL = "data:image/png;base64,abc123";

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("LocalizedImage - loading state", () => {
  test("shows loading placeholder while fetching", async () => {
    // Never resolves during this test
    mockLocalizeImage.mockReturnValue(new Promise(() => {}));
    render(<LocalizedImage url={URL} alt="test" token={TOKEN} />);
    expect(screen.getByTestId("localized-image-loading")).toBeInTheDocument();
    expect(screen.getByTestId("localized-image-loading")).toHaveAttribute("aria-busy", "true");
  });
});

describe("LocalizedImage - success path", () => {
  test("renders <img> with data_url on success", async () => {
    mockLocalizeImage.mockResolvedValue({ ok: true, data_url: DATA_URL });
    render(<LocalizedImage url={URL} alt="my photo" token={TOKEN} />);
    const img = await screen.findByTestId("localized-image");
    expect(img.tagName).toBe("IMG");
    expect(img).toHaveAttribute("src", DATA_URL);
    expect(img).toHaveAttribute("alt", "my photo");
    expect(img).toHaveAttribute("loading", "lazy");
    // Ensure the original URL is NEVER in an img src (no-egress invariant)
    const allImgs = document.querySelectorAll("img");
    allImgs.forEach((i) => expect(i.getAttribute("src")).not.toBe(URL));
  });

  test("calls localizeImage with the correct token and url", async () => {
    mockLocalizeImage.mockResolvedValue({ ok: true, data_url: DATA_URL });
    render(<LocalizedImage url={URL} token={TOKEN} />);
    await screen.findByTestId("localized-image");
    expect(mockLocalizeImage).toHaveBeenCalledWith(TOKEN, URL);
  });
});

describe("LocalizedImage - needs_approval path", () => {
  test("renders consent card with host name", async () => {
    mockLocalizeImage.mockResolvedValue({
      ok: false,
      needs_approval: true,
      host: "upload.wikimedia.org",
    });
    render(<LocalizedImage url={URL} token={TOKEN} />);
    await screen.findByTestId("localized-image-approve");
    expect(screen.getByTestId("localized-image-approve")).toBeInTheDocument();
    expect(screen.getByTestId("localized-image-deny")).toBeInTheDocument();
    // Should show the host name in the consent text
    expect(screen.getByText(/upload\.wikimedia\.org/)).toBeInTheDocument();
  });

  test("Allow: calls allowEgressHost then retries localizeImage -> shows img", async () => {
    mockLocalizeImage
      .mockResolvedValueOnce({ ok: false, needs_approval: true, host: "upload.wikimedia.org" })
      .mockResolvedValueOnce({ ok: true, data_url: DATA_URL });
    mockAllowEgressHost.mockResolvedValue(undefined);

    render(<LocalizedImage url={URL} token={TOKEN} />);
    const approveBtn = await screen.findByTestId("localized-image-approve");
    fireEvent.click(approveBtn);

    await waitFor(() =>
      expect(mockAllowEgressHost).toHaveBeenCalledWith(TOKEN, "upload.wikimedia.org"),
    );
    await waitFor(() => expect(mockLocalizeImage).toHaveBeenCalledTimes(2));

    const img = await screen.findByTestId("localized-image");
    expect(img.tagName).toBe("IMG");
    expect(img).toHaveAttribute("src", DATA_URL);
  });

  test("Allow then second localize returns error -> shows fallback link", async () => {
    mockLocalizeImage
      .mockResolvedValueOnce({ ok: false, needs_approval: true, host: "upload.wikimedia.org" })
      .mockResolvedValueOnce({ ok: false, error: "blocked" });
    mockAllowEgressHost.mockResolvedValue(undefined);

    render(<LocalizedImage url={URL} alt="img" token={TOKEN} />);
    const approveBtn = await screen.findByTestId("localized-image-approve");
    fireEvent.click(approveBtn);

    const fallback = await screen.findByTestId("localized-image-fallback");
    expect(fallback.tagName).toBe("A");
    expect(fallback).toHaveAttribute("href", URL);
    expect(fallback).toHaveAttribute("rel", "noopener noreferrer");
  });

  test("Deny: clicking Don't allow shows fallback link to original url", async () => {
    mockLocalizeImage.mockResolvedValue({
      ok: false,
      needs_approval: true,
      host: "upload.wikimedia.org",
    });
    render(<LocalizedImage url={URL} alt="my image" token={TOKEN} />);
    const denyBtn = await screen.findByTestId("localized-image-deny");
    fireEvent.click(denyBtn);

    const fallback = screen.getByTestId("localized-image-fallback");
    expect(fallback.tagName).toBe("A");
    expect(fallback).toHaveAttribute("href", URL);
    expect(fallback).toHaveAttribute("rel", "noopener noreferrer");
    // Original URL must NOT appear in any img src
    const imgs = document.querySelectorAll("img");
    imgs.forEach((i) => expect(i.getAttribute("src")).not.toBe(URL));
  });
});

describe("LocalizedImage - error path", () => {
  test("renders fallback link on api error", async () => {
    mockLocalizeImage.mockResolvedValue({ ok: false, error: "fetch failed" });
    render(<LocalizedImage url={URL} alt="broken" token={TOKEN} />);
    const fallback = await screen.findByTestId("localized-image-fallback");
    expect(fallback.tagName).toBe("A");
    expect(fallback).toHaveAttribute("href", URL);
    expect(fallback).toHaveAttribute("rel", "noopener noreferrer");
    expect(fallback).toHaveTextContent("broken");
  });

  test("fallback link never puts remote URL in img src", async () => {
    mockLocalizeImage.mockResolvedValue({ ok: false, error: "blocked" });
    render(<LocalizedImage url={URL} token={TOKEN} />);
    await screen.findByTestId("localized-image-fallback");
    const imgs = document.querySelectorAll("img");
    imgs.forEach((i) => expect(i.getAttribute("src")).not.toBe(URL));
  });
});
