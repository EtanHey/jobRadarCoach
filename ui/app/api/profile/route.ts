import {
  ProfilePatchSchema, ProfileResponseSchema,
} from "../../../lib/contracts";
import { mutationJson, output, safely } from "../../../lib/http";
import { getApiStore, type ApiStore } from "../../../lib/server";

export function makeGetProfile(store: ApiStore) {
  return () => safely(async () => {
    return output(ProfileResponseSchema, { profile: await store.getProfile() });
  });
}

export function makePatchProfile(store: ApiStore) {
  return (request: Request) => safely(async () => {
    const patch = await mutationJson(request, ProfilePatchSchema);
    return output(ProfileResponseSchema, { profile: await store.updateProfile(patch) });
  });
}

export function GET(): Promise<Response> {
  return makeGetProfile(getApiStore())();
}

export function PATCH(request: Request): Promise<Response> {
  return makePatchProfile(getApiStore())(request);
}
