import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { FolderAddForm } from "./FolderAddForm";
import type { AddFolderResult } from "./useFolderSources";

const ok = (): Promise<AddFolderResult> => Promise.resolve({ ok: true });
const fail = (code: string, message: string): Promise<AddFolderResult> =>
  Promise.resolve({ ok: false, error: { code, message } });

test("submits the trimmed path + label and clears on success", async () => {
  const onAdd = vi.fn(ok);
  render(<FolderAddForm onAdd={onAdd} />);

  fireEvent.change(screen.getByTestId("folder-add-path"), {
    target: { value: "  /Users/me/notes  " },
  });
  fireEvent.change(screen.getByTestId("folder-add-label"), { target: { value: "Notes" } });
  fireEvent.click(screen.getByTestId("folder-add-submit"));

  await waitFor(() => expect(onAdd).toHaveBeenCalledWith("/Users/me/notes", "Notes"));
  // Inputs clear on success.
  await waitFor(() => expect(screen.getByTestId("folder-add-path")).toHaveValue(""));
  expect(screen.getByTestId("folder-add-label")).toHaveValue("");
  expect(screen.queryByTestId("folder-add-error")).toBeNull();
});

test("Add is disabled until a path is entered", () => {
  render(<FolderAddForm onAdd={vi.fn(ok)} />);
  expect(screen.getByTestId("folder-add-submit")).toBeDisabled();
  fireEvent.change(screen.getByTestId("folder-add-path"), { target: { value: "/x" } });
  expect(screen.getByTestId("folder-add-submit")).toBeEnabled();
});

test.each([
  ["E_FOLDER_NOT_FOUND", "That folder does not exist."],
  ["E_FOLDER_NOT_A_DIR", "That path is not a directory."],
  ["E_FOLDER_EXISTS", "That folder is already registered."],
])("renders the inline message for %s", async (code, message) => {
  const onAdd = vi.fn(() => fail(code, message));
  render(<FolderAddForm onAdd={onAdd} />);

  fireEvent.change(screen.getByTestId("folder-add-path"), { target: { value: "/bad/path" } });
  fireEvent.click(screen.getByTestId("folder-add-submit"));

  await waitFor(() => expect(screen.getByTestId("folder-add-error")).toHaveTextContent(message));
  // The path is preserved on error so the user can correct it.
  expect(screen.getByTestId("folder-add-path")).toHaveValue("/bad/path");
});

test("disables inputs + submit when offline", () => {
  render(<FolderAddForm onAdd={vi.fn(ok)} disabled />);
  expect(screen.getByTestId("folder-add-path")).toBeDisabled();
  expect(screen.getByTestId("folder-add-submit")).toBeDisabled();
});
