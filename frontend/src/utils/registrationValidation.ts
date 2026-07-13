export type RegistrationInputField =
  | 'username'
  | 'displayName'
  | 'email'
  | 'password'
  | 'confirmPassword'

export type RegistrationErrorField = RegistrationInputField | 'form'

export type RegistrationErrors = Partial<Record<RegistrationErrorField, string>>

export interface RegistrationValues {
  username: string
  displayName: string
  email: string
  password: string
  confirmPassword: string
}

export interface RegistrationValidationMessages {
  usernameRequired: string
  usernameTooShort: string
  usernameTooLong: string
  usernameWhitespace: string
  displayNameTooLong: string
  emailRequired: string
  emailInvalid: string
  emailTooLong: string
  passwordRequired: string
  passwordTooShort: string
  passwordTooLong: string
  confirmPasswordRequired: string
  passwordMismatch: string
}

const BASIC_EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

const registrationFieldOrder: RegistrationErrorField[] = [
  'username',
  'displayName',
  'email',
  'password',
  'confirmPassword',
  'form',
]

const serverFieldMap: Record<string, RegistrationInputField> = {
  username: 'username',
  display_name: 'displayName',
  email: 'email',
  password: 'password',
  confirm_password: 'confirmPassword',
}

export const validateRegistration = (
  values: RegistrationValues,
  messages: RegistrationValidationMessages,
): RegistrationErrors => {
  const errors: RegistrationErrors = {}
  const username = values.username.trim()
  const displayName = values.displayName.trim()
  const email = values.email.trim()

  if (!username) errors.username = messages.usernameRequired
  else if (username.length < 3) errors.username = messages.usernameTooShort
  else if (username.length > 128) errors.username = messages.usernameTooLong
  else if (/\s/.test(username)) errors.username = messages.usernameWhitespace

  if (displayName.length > 128) errors.displayName = messages.displayNameTooLong

  if (!email) errors.email = messages.emailRequired
  else if (email.length > 255) errors.email = messages.emailTooLong
  else if (!BASIC_EMAIL_PATTERN.test(email)) errors.email = messages.emailInvalid

  if (!values.password) errors.password = messages.passwordRequired
  else if (values.password.length < 6) errors.password = messages.passwordTooShort
  else if (values.password.length > 256) errors.password = messages.passwordTooLong

  if (!values.confirmPassword) errors.confirmPassword = messages.confirmPasswordRequired
  else if (values.password !== values.confirmPassword) {
    errors.confirmPassword = messages.passwordMismatch
  }

  return errors
}

const serverFieldFromLocation = (location: unknown): RegistrationInputField | undefined => {
  if (!Array.isArray(location)) return undefined
  for (let index = location.length - 1; index >= 0; index -= 1) {
    const key = String(location[index] ?? '')
    if (serverFieldMap[key]) return serverFieldMap[key]
  }
  return undefined
}

const assignValidationItems = (detail: unknown[], errors: RegistrationErrors) => {
  for (const item of detail) {
    if (!item || typeof item !== 'object') continue
    const validationItem = item as { loc?: unknown; msg?: unknown }
    const field = serverFieldFromLocation(validationItem.loc)
    const message = typeof validationItem.msg === 'string' ? validationItem.msg : ''
    if (field && message && !errors[field]) errors[field] = message
  }
}

const assignValidationString = (detail: string, errors: RegistrationErrors) => {
  const fieldPattern = /(?:^|;\s*)(?:body\.)?(username|display_name|email|password|confirm_password)\s*:\s*([^;]+)/gi
  for (const match of detail.matchAll(fieldPattern)) {
    const field = serverFieldMap[match[1].toLowerCase()]
    const message = match[2]?.trim()
    if (field && message && !errors[field]) errors[field] = message
  }
}

/**
 * Convert the registration endpoint's FastAPI/Axios error shapes into errors
 * that can be rendered beside their owning controls. A custom registration
 * email policy can contain arbitrary administrator-provided copy, so an
 * otherwise-unclassified 400 response is assigned to email: at this endpoint
 * that is the only custom validation message evaluated before user creation.
 */
export const mapRegistrationServerError = (
  error: unknown,
  fallback: string,
): RegistrationErrors => {
  const candidate = error as {
    message?: unknown
    response?: {
      status?: unknown
      data?: { detail?: unknown; message?: unknown; error_code?: unknown }
    }
  }
  const status = Number(candidate?.response?.status)
  const body = candidate?.response?.data
  const detail = body?.detail
  const errors: RegistrationErrors = {}

  if (Array.isArray(detail)) assignValidationItems(detail, errors)
  else if (typeof detail === 'string') assignValidationString(detail, errors)
  if (Object.keys(errors).length) return errors

  const detailText = typeof detail === 'string' ? detail.trim() : ''
  const messageText = typeof body?.message === 'string' ? body.message.trim() : ''
  const errorText = typeof candidate?.message === 'string' ? candidate.message.trim() : ''
  const message = detailText || messageText || errorText || fallback

  if (status === 400) {
    if (/^\u7528\u6237\u540d\u5df2\u5b58\u5728$|^username (?:already )?exists$/i.test(message)) {
      return { username: message }
    }
    if (/\u4fdd\u5b58\u7528\u6237\u5931\u8d25|failed to save user/i.test(message)) return { form: message }
    // The endpoint's remaining 400 responses come from the baseline email
    // check or its administrator-authored policy. Do this before keyword
    // inference because custom copy may itself mention username or password.
    return { email: message }
  }

  if (/\u7528\u6237\u540d|user\s*name|username/i.test(message)) return { username: message }
  if (/\u5c55\u793a\u540d|display[\s_-]*name/i.test(message)) return { displayName: message }
  if (/\u90ae\u7bb1|\u7535\u5b50\u90ae\u4ef6|e-?mail/i.test(message)) return { email: message }
  if (/\u786e\u8ba4\u5bc6\u7801|confirm[\s_-]*password/i.test(message)) return { confirmPassword: message }
  if (/\u5bc6\u7801|password/i.test(message)) return { password: message }
  return { form: message }
}

export const firstRegistrationErrorField = (
  errors: RegistrationErrors,
): RegistrationErrorField | undefined => registrationFieldOrder.find((field) => Boolean(errors[field]))
