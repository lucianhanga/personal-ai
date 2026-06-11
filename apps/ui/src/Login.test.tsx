import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import * as api from "./api";
import { Login } from "./Login";

afterEach(() => vi.restoreAllMocks());

test("logs in and calls onAuthed", async () => {
  const loginSpy = vi.spyOn(api, "login").mockResolvedValue();
  const onAuthed = vi.fn();
  render(<Login onAuthed={onAuthed} />);

  fireEvent.change(screen.getByTestId("login-email"), { target: { value: "a@example.com" } });
  fireEvent.change(screen.getByTestId("login-password"), { target: { value: "pw" } });
  fireEvent.click(screen.getByTestId("login-submit"));

  await waitFor(() => expect(onAuthed).toHaveBeenCalled());
  expect(loginSpy).toHaveBeenCalledWith("a@example.com", "pw");
});

test("signup mode calls signup then login", async () => {
  const signupSpy = vi.spyOn(api, "signup").mockResolvedValue();
  vi.spyOn(api, "login").mockResolvedValue();
  const onAuthed = vi.fn();
  render(<Login onAuthed={onAuthed} />);

  fireEvent.click(screen.getByTestId("login-toggle")); // switch to signup
  fireEvent.change(screen.getByTestId("login-email"), { target: { value: "new@example.com" } });
  fireEvent.change(screen.getByTestId("login-password"), { target: { value: "pw" } });
  fireEvent.click(screen.getByTestId("login-submit"));

  await waitFor(() => expect(onAuthed).toHaveBeenCalled());
  expect(signupSpy).toHaveBeenCalledWith("new@example.com", "pw");
});

test("shows an error on bad credentials and does not call onAuthed", async () => {
  vi.spyOn(api, "login").mockRejectedValue(new Error("invalid credentials"));
  const onAuthed = vi.fn();
  render(<Login onAuthed={onAuthed} />);

  fireEvent.change(screen.getByTestId("login-email"), { target: { value: "a@example.com" } });
  fireEvent.change(screen.getByTestId("login-password"), { target: { value: "bad" } });
  fireEvent.click(screen.getByTestId("login-submit"));

  expect(await screen.findByTestId("login-error")).toHaveTextContent(/invalid/i);
  expect(onAuthed).not.toHaveBeenCalled();
});
