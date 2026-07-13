import { describe, expect, it } from 'vitest'

import {
  firstRegistrationErrorField,
  mapRegistrationServerError,
  validateRegistration,
  type RegistrationValidationMessages,
} from './registrationValidation'

const messages: RegistrationValidationMessages = {
  usernameRequired: 'username required',
  usernameTooShort: 'username too short',
  usernameTooLong: 'username too long',
  usernameWhitespace: 'username contains whitespace',
  displayNameTooLong: 'display name too long',
  emailRequired: 'email required',
  emailInvalid: 'email invalid',
  emailTooLong: 'email too long',
  passwordRequired: 'password required',
  passwordTooShort: 'password too short',
  passwordTooLong: 'password too long',
  confirmPasswordRequired: 'confirmation required',
  passwordMismatch: 'passwords do not match',
}

describe('registration validation', () => {
  it('returns every relevant field error instead of stopping at the first one', () => {
    const errors = validateRegistration({
      username: '',
      displayName: '',
      email: '',
      password: '123',
      confirmPassword: '321',
    }, messages)

    expect(errors).toEqual({
      username: 'username required',
      email: 'email required',
      password: 'password too short',
      confirmPassword: 'passwords do not match',
    })
    expect(firstRegistrationErrorField(errors)).toBe('username')
  })

  it('matches the backend baseline email and username rules', () => {
    const errors = validateRegistration({
      username: 'bad name',
      displayName: '',
      email: 'not-an-email',
      password: 'secret123',
      confirmPassword: 'secret123',
    }, messages)

    expect(errors.username).toBe('username contains whitespace')
    expect(errors.email).toBe('email invalid')
    expect(errors.password).toBeUndefined()
  })
})

describe('registration server error mapping', () => {
  it('places an arbitrary administrator email-policy message on email', () => {
    const errors = mapRegistrationServerError({
      response: { status: 400, data: { detail: '用户名需使用公司邮箱前缀，请勿填写个人密码' } },
    }, 'fallback')

    expect(errors).toEqual({ email: '用户名需使用公司邮箱前缀，请勿填写个人密码' })
  })

  it('places a duplicate username response on username', () => {
    const errors = mapRegistrationServerError({
      response: { status: 400, data: { detail: '用户名已存在' } },
    }, 'fallback')

    expect(errors).toEqual({ username: '用户名已存在' })
  })

  it('maps FastAPI validation items to their fields', () => {
    const errors = mapRegistrationServerError({
      response: {
        status: 422,
        data: {
          detail: [
            { loc: ['body', 'username'], msg: 'String should have at least 3 characters' },
            { loc: ['body', 'password'], msg: 'String should have at least 6 characters' },
          ],
        },
      },
    }, 'fallback')

    expect(errors).toEqual({
      username: 'String should have at least 3 characters',
      password: 'String should have at least 6 characters',
    })
  })

  it('maps the production validation error string to its fields', () => {
    const errors = mapRegistrationServerError({
      response: {
        status: 422,
        data: {
          message: '请求参数验证失败',
          detail: 'body.username: Value error, 用户名不能包含空白字符; body.password: String should have at least 6 characters',
        },
      },
    }, 'fallback')

    expect(errors).toEqual({
      username: 'Value error, 用户名不能包含空白字符',
      password: 'String should have at least 6 characters',
    })
  })

  it('keeps non-field failures inside the form', () => {
    const errors = mapRegistrationServerError({
      response: { status: 500, data: { message: 'Service unavailable' } },
    }, 'fallback')

    expect(errors).toEqual({ form: 'Service unavailable' })
  })
})
