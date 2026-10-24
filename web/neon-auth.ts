import { createAuthClient } from "@neondatabase/auth";

Object.assign(window, {
  createKnowraNeonAuth: (url: string) => createAuthClient(url),
});
