import { initials, avatarClass } from '../utils/avatar'

export default function Avatar({ name, size = 26 }) {
  return (
    <span
      className={`av ${avatarClass(name)}`}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }}
    >
      {initials(name)}
    </span>
  )
}
