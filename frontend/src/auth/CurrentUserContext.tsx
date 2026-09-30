import { createContext, useContext } from "react";
import type { AppUser } from "./types";

export const CurrentUserContext = createContext<AppUser | null>(null);

export function useCurrentUser(): AppUser | null {
  return useContext(CurrentUserContext);
}
