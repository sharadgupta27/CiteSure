import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginPage } from "./LoginPage";

const signIn = vi.fn();
const signInWithToken = vi.fn();
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ signIn, signInWithToken, user: null, loading: false, signOut: vi.fn() }) }));

let authConfig: object | undefined;
vi.mock("../api/hooksAdmin", () => ({ useAuthConfig: () => ({ data: authConfig }) }));

beforeEach(() => {
  signIn.mockReset(); // braces matter: a returned function would be run by vitest as a teardown hook
  signInWithToken.mockReset();
  authConfig = undefined;
  window.history.replaceState(null, "", "/");
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

  it("offers single sign-on only when the server says it is enabled", async () => {
    const { unmount } = render(<LoginPage />);
    expect(screen.queryByRole("link", { name: /sign in with/i })).not.toBeInTheDocument();
    unmount();

    authConfig = { password_login: true, registration: true, oidc_enabled: true, oidc_provider_name: "Acme Keycloak" };
    render(<LoginPage />);
    const link = screen.getByRole("link", { name: "Sign in with Acme Keycloak" });
    expect(link).toHaveAttribute("href", "/api/v1/auth/oidc/login");
    expect(screen.getByLabelText("Password")).toBeInTheDocument(); // password sign-in stays unless OIDC_ONLY
  });

  it("hides the password form and registration when the server is OIDC-only", () => {
    authConfig = { password_login: false, registration: false, oidc_enabled: true, oidc_provider_name: "Entra" };
    render(<LoginPage />);
    expect(screen.getByRole("link", { name: "Sign in with Entra" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create an account" })).not.toBeInTheDocument();
  });

  it("completes a single sign-on from the URL fragment and removes the token from the address bar", async () => {
    signInWithToken.mockResolvedValue(undefined);
    window.history.replaceState(null, "", "/#oidc_token=abc.def.ghi");
    render(<LoginPage />);
    await waitFor(() => expect(signInWithToken).toHaveBeenCalledWith("abc.def.ghi"));
    expect(window.location.hash).toBe("");
  });

  it("explains a failed single sign-on", async () => {
    window.history.replaceState(null, "", "/#oidc_error=no_account");
    render(<LoginPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("no CiteSure account");
    expect(signInWithToken).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
  });
});
