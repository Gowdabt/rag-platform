export type AppUser = {
  user_id?: string;
  email?: string;
  name?: string | null;
  tenant_id?: string | null;
  tenant_name?: string | null;
  tenant_slug?: string | null;
  is_super_admin?: boolean;
  roles?: Array<string | { name?: string; slug?: string }>;
  permissions?: string[];
};
