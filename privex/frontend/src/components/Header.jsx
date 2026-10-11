import styles from './Header.module.css'

export default function Header({ health }) {
  const online = health === null ? null : !!health

  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <div className={styles.logo}>
          <span className={styles.dot} />
          PRIVEX
        </div>
        <div className={styles.right}>
          <span className={styles.tagline}>Local Privacy Firewall</span>
          <span className={`${styles.status} ${online === true ? styles.ok : online === false ? styles.err : styles.checking}`}>
            {online === null ? '◌ CONNECTING' : online ? '● ENGINE ONLINE' : '✕ ENGINE OFFLINE'}
          </span>
        </div>
      </div>
    </header>
  )
}
