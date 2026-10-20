import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginPage } from "./LoginPage";

const signIn = vi.fn();
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ signIn, user: null, loading: false, signOut: vi.fn() }) }));

beforeEach(() => {
  signIn.mockReset(); // braces matter: a returned function would be run by vitest as a teardown hook
});

describe("LoginPage", () => {
  it("signs in with the entered credentials", async () => {
    signIn.mockResolvedValue(undefined);
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Email"), "employee@acme.example");
    await userEvent.type(screen.getByLabelText("Password"), "citesure-demo");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(signIn).toHaveBeenCalledWith("employee@acme.example", "citesure-demo", false);
  });

  it("shows the server's error message and stays on the page", async () => {
    signIn.mockRejectedValue(new Error("Wrong email or password"));
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password");
  });

  it("switches to account creation", async () => {
    signIn.mockResolvedValue(undefined);
    render(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: "Create an account" }));
    await userEvent.type(screen.getByLabelText("Email"), "new@acme.example");
    await userEvent.type(screen.getByLabelText("Password"), "a-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(signIn).toHaveBeenCalledWith("new@acme.example", "a-long-password", true));
  });
});
